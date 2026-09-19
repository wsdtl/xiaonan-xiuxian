from __future__ import annotations

from collections.abc import Mapping

from game.core.asset import AssetService, InventoryAdjustment, InventoryChangeError
from game.core.character import CharacterCultivationError, CharacterService
from game.core.companion import CompanionCultivationError, CompanionService
from game.core.data import JsonDataError, JsonDataService, nonempty_text as _text
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    StateConflictError,
    TransactionCommand,
)
from game.core.location import LocationService
from game.core.medicine import MedicineError, MedicineService
from game.core.player_state import PlayerStateService
from game.core.world import LocationQuery, WorldService

from .contracts import ButianConflictError, ButianError, ButianResult


class ButianFeature:
    def __init__(self, data: JsonDataService, medicine: MedicineService, character: CharacterService, companion: CompanionService, asset: AssetService, player_state: PlayerStateService, location: LocationService, world: WorldService, database: DatabaseService) -> None:
        self._data, self._medicine, self._character, self._companion, self._asset = data, medicine, character, companion, asset
        self._player_state, self._location, self._world, self._database = player_state, location, world, database
        self._copy: Mapping[str, object] | None = None
        self._medicine_id = ""
        self._location_function = ""
        self._guard_rule = ""

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("补天玩法已经初始化")
        rule = self._world.feature_config("补天")
        self._medicine_id = _text(rule.get("丹药"), "补天.丹药")
        self._location_function = "补天"
        self._guard_rule = _text(rule.get("状态守卫"), "补天.状态守卫")
        copy = self._data.dataset("补天展示").get("文本")
        if not isinstance(copy, Mapping):
            raise JsonDataError("补天展示缺少文本.json")
        self._copy = copy

    def copy(self, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
        if self._copy is None:
            raise RuntimeError("补天玩法尚未初始化")
        group = self._copy.get(section)
        value = group.get(key) if isinstance(group, Mapping) else None
        if not isinstance(value, str):
            raise JsonDataError(f"补天展示缺少文本：{section}.{key}")
        return value.format_map(values or {})

    async def apply(self, user_id: str, request_id: str, target: str, realm: str, source_medicine_id: str) -> ButianResult:
        target = str(target or "").strip()
        if target not in {"人物", "道侣"}:
            raise ButianError("补天目标只能是人物或道侣")
        source_query = str(source_medicine_id or "").strip()
        requested_realm = str(realm or "").strip()
        if not requested_realm:
            raise ButianError("必须指定要补正的境界")
        if not source_query:
            raise ButianError("必须指定同境界单属性突破丹")
        try:
            source = self._medicine.resolve(source_query)
        except MedicineError as exc:
            raise ButianError(str(exc)) from exc
        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != "九霄补天":
                raise ButianConflictError("请求编号已经用于其他操作")
            if committed.payload.get("请求目标") != target or committed.payload.get("请求境界") != requested_realm or committed.payload.get("请求来源丹药") != source:
                raise ButianConflictError("补天请求与已提交事务不一致")
            return _result(committed.payload, True)
        await self._context(user_id)
        try:
            if target == "人物":
                plan = await self._character.plan_breakthrough_correction(user_id, source_medicine_id=source)
                target_name = (await self._character.profile(user_id)).name
                operations = (plan.operation,)
                attrs = plan.attributes
                realm = plan.target_realm
            else:
                plan = await self._companion.plan_breakthrough_correction(user_id, source_medicine_id=source)
                target_name = self._companion.definition(plan.companion_id).name
                operations = plan.operations
                attrs = plan.attributes
                realm = plan.target_realm
            realm_raw = self._data.entity("境界", realm)
            realm_name = str(realm_raw.get("名称") or realm)
            if requested_realm not in {realm, realm_name}:
                raise ButianError(f"当前可补正的突破节点是{realm_name}")
            stack = await self._lowest_stack(user_id, self._medicine_id)
            if stack is None:
                raise ButianError("纳戒中没有九霄补天丹")
            inventory = await self._asset.plan_inventory_changes(user_id, (InventoryAdjustment(self._medicine_id, stack.grade.grade_id, -1),))
            attribute, value = attrs[0]
            payload = {"请求目标": target, "请求境界": requested_realm, "请求来源丹药": source, "目标": target, "目标名称": target_name, "境界": realm_name, "属性": attribute, "数值": value, "丹药名称": str(self._data.entity("丹药", self._medicine_id).get("名称") or "九霄补天丹")}
            receipt = await self._database.commit(TransactionCommand(user_id, request_id, "九霄补天", inventory.operations + operations, payload))
        except (InventoryChangeError, CharacterCultivationError, CompanionCultivationError, StateConflictError) as exc:
            raise ButianError(str(exc)) from exc
        except IdempotencyConflictError as exc:
            raise ButianConflictError("请求编号已经用于其他操作") from exc
        return _result(payload, receipt.replayed)

    async def _authorize(self, user_id: str) -> None:
        result = await self._player_state.authorize(user_id, self._guard_rule)
        if not result.allowed:
            raise ButianError(result.reason)

    async def _context(self, user_id: str) -> None:
        await self._authorize(user_id)
        current = await self._location.current(user_id)
        place = self._world.locate(LocationQuery(xy=current.xy))
        if self._location_function not in place.available_functions:
            raise ButianError("只有身在裂天原才能使用补天丹")

    async def _lowest_stack(self, user_id: str, item_id: str):
        stacks = await self._asset.inventory_stacks(user_id, item_id)
        return min(stacks, key=lambda value: value.grade.order) if stacks else None


def _result(value: Mapping[str, object], replayed: bool) -> ButianResult:
    return ButianResult(str(value.get("目标") or ""), str(value.get("目标名称") or ""), str(value.get("境界") or ""), str(value.get("属性") or ""), float(value.get("数值") or 0), str(value.get("丹药名称") or ""), replayed)


__all__ = ["ButianFeature"]
