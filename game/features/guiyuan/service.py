from __future__ import annotations

from collections.abc import Mapping

from game.core.asset import AssetService, InventoryAdjustment, InventoryChangeError
from game.core.companion import CompanionCultivationError, CompanionService
from game.core.data import JsonDataError, JsonDataService, nonempty_text as _text
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    StateConflictError,
    TransactionCommand,
)
from game.core.location import LocationError, LocationService
from game.core.medicine import MedicineService
from game.core.player_state import PlayerStateService
from game.core.world import LocationQuery, WorldService

from .contracts import GuiyuanConflictError, GuiyuanError, GuiyuanPreview, GuiyuanResult


class GuiyuanFeature:
    def __init__(self, data: JsonDataService, medicine: MedicineService, companion: CompanionService, asset: AssetService, player_state: PlayerStateService, location: LocationService, world: WorldService, database: DatabaseService) -> None:
        self._data, self._medicine, self._companion, self._asset = data, medicine, companion, asset
        self._player_state, self._location, self._world, self._database = player_state, location, world, database
        self._copy: Mapping[str, object] | None = None
        self._medicine_id = ""
        self._location_function = ""
        self._guard_rule = ""

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("归元玩法已经初始化")
        if not self._medicine.status().initialized or not self._companion.status().initialized:
            raise RuntimeError("丹药核心和道侣核心必须先于归元玩法启动")
        rule = self._world.feature_config("归元")
        self._medicine_id = _text(rule.get("丹药"), "归元观.丹药")
        self._location_function = "归元"
        self._guard_rule = _text(rule.get("状态守卫"), "归元观.状态守卫")
        copy = self._data.dataset("归元展示").get("文本")
        if not isinstance(copy, Mapping):
            raise JsonDataError("归元展示缺少文本.json")
        self._copy = copy

    def copy(self, section: str, key: str, **values: object) -> str:
        if self._copy is None:
            raise RuntimeError("归元玩法尚未初始化")
        group = self._copy.get(section)
        value = group.get(key) if isinstance(group, Mapping) else None
        if not isinstance(value, str):
            raise JsonDataError(f"归元展示缺少文本：{section}.{key}")
        return value.format_map(values)

    async def preview(self, user_id: str) -> GuiyuanPreview:
        context = await self._context(user_id)
        instance = await self._companion.active_instance(user_id)
        stacks = await self._asset.inventory_stacks(user_id, self._medicine_id)
        return GuiyuanPreview(context["location"], context["name"], context["medicine"], bool(stacks), tuple((key, len(value)) for key, value in instance.instance.cultivation.items()))

    async def reset(self, user_id: str, request_id: str, category: str) -> GuiyuanResult:
        normalized = str(category or "").strip()
        if normalized not in {"功法", "真意", "气机"}:
            raise GuiyuanError("归元类别只能是功法、真意或气机")
        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != "万法归元":
                raise GuiyuanConflictError("请求编号已经用于其他操作")
            if committed.payload.get("类别") != normalized:
                raise GuiyuanConflictError("归元类别与已提交事务不一致")
            return _result(committed.payload, True)
        context = await self._context(user_id)
        stack = await self._medicine_stack(user_id)
        if stack is None:
            raise GuiyuanError("纳戒中没有万法归元丹")
        try:
            plan = await self._companion.plan_build_reset(user_id, category=normalized)
            inventory = await self._asset.plan_inventory_changes(user_id, (InventoryAdjustment(self._medicine_id, stack.grade.grade_id, -1),))
            payload = {"道侣名称": context["name"], "类别": normalized, "数量": len(plan.content_ids), "丹药名称": context["medicine"]}
            receipt = await self._database.commit(TransactionCommand(user_id, request_id, "万法归元", inventory.operations + plan.operations, payload))
        except (InventoryChangeError, CompanionCultivationError, StateConflictError) as exc:
            raise GuiyuanError(str(exc)) from exc
        except IdempotencyConflictError as exc:
            raise GuiyuanConflictError("请求编号已经用于其他操作") from exc
        return _result(payload, receipt.replayed)

    async def _context(self, user_id: str) -> dict[str, str]:
        await self._authorize(user_id)
        try:
            current = await self._location.current(user_id)
            place = self._world.locate(LocationQuery(xy=current.xy))
            if self._location_function not in place.available_functions:
                raise GuiyuanError("只有身在归元观才能使用归元丹")
            active = await self._companion.active_instance(user_id)
        except (LocationError, CompanionCultivationError) as exc:
            raise GuiyuanError(str(exc)) from exc
        return {"location": place.location_name, "name": self._companion.definition(active.instance.companion_id).name, "medicine": str(self._medicine_raw().get("名称") or "万法归元丹")}

    async def _authorize(self, user_id: str) -> None:
        result = await self._player_state.authorize(user_id, self._guard_rule)
        if not result.allowed:
            raise GuiyuanError(result.reason)

    async def _medicine_stack(self, user_id: str):
        stacks = await self._asset.inventory_stacks(user_id, self._medicine_id)
        return min(stacks, key=lambda value: value.grade.order) if stacks else None

    def _medicine_raw(self):
        return self._data.entity("丹药", self._medicine_id)


def _result(payload: Mapping[str, object], replayed: bool) -> GuiyuanResult:
    return GuiyuanResult(str(payload.get("道侣名称") or ""), str(payload.get("类别") or ""), int(payload.get("数量") or 0), str(payload.get("丹药名称") or ""), replayed)


__all__ = ["GuiyuanFeature"]
