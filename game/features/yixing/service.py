from __future__ import annotations

from collections.abc import Mapping

from game.core.asset import AssetService, InventoryAdjustment, InventoryChangeError
from game.core.character import CharacterCultivationError, CharacterService
from game.core.data import JsonDataError, JsonDataService, nonempty_text as _text
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    StateConflictError,
    TransactionCommand,
)
from game.core.location import LocationService
from game.core.medicine import MedicineService
from game.core.player_state import PlayerStateService
from game.core.world import LocationQuery, WorldService

from .contracts import YixingConflictError, YixingError, YixingResult


class YixingFeature:
    def __init__(self, data: JsonDataService, medicine: MedicineService, character: CharacterService, asset: AssetService, player_state: PlayerStateService, location: LocationService, world: WorldService, database: DatabaseService) -> None:
        self._data, self._medicine, self._character, self._asset = data, medicine, character, asset
        self._player_state, self._location, self._world, self._database = player_state, location, world, database
        self._copy: Mapping[str, object] | None = None
        self._medicine_id = ""
        self._location_function = ""
        self._guard_rule = ""

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("易形玩法已经初始化")
        rule = self._world.feature_config("易形")
        self._medicine_id = _text(rule.get("丹药"), "易形.丹药")
        self._location_function = "易形"
        self._guard_rule = _text(rule.get("状态守卫"), "易形.状态守卫")
        copy = self._data.dataset("易形展示").get("文本")
        if not isinstance(copy, Mapping):
            raise JsonDataError("易形展示缺少文本.json")
        self._copy = copy

    def copy(self, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
        if self._copy is None:
            raise RuntimeError("易形玩法尚未初始化")
        group = self._copy.get(section)
        value = group.get(key) if isinstance(group, Mapping) else None
        if not isinstance(value, str):
            raise JsonDataError(f"易形展示缺少文本：{section}.{key}")
        return value.format_map(values or {})

    async def change(self, user_id: str, request_id: str) -> YixingResult:
        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != "两仪易形":
                raise YixingConflictError("请求编号已经用于其他操作")
            return _result(committed.payload, True)
        await self._authorize(user_id)
        try:
            current = await self._location.current(user_id)
            place = self._world.locate(LocationQuery(xy=current.xy))
            if self._location_function not in place.available_functions:
                raise YixingError("只有身在太素坊才能使用易形丹")
            plan = await self._character.plan_gender_change(user_id)
            profile = await self._character.profile(user_id)
            stacks = await self._asset.inventory_stacks(user_id, self._medicine_id)
            if not stacks:
                raise YixingError("纳戒中没有两仪易形丹")
            stack = min(stacks, key=lambda value: value.grade.order)
            inventory = await self._asset.plan_inventory_changes(user_id, (InventoryAdjustment(self._medicine_id, stack.grade.grade_id, -1),))
            payload = {"人物名称": profile.name, "原性别": plan.gender_before, "新性别": plan.gender_after, "丹药名称": str(self._data.entity("丹药", self._medicine_id).get("名称") or "两仪易形丹")}
            receipt = await self._database.commit(TransactionCommand(user_id, request_id, "两仪易形", inventory.operations + (plan.operation,), payload))
        except (InventoryChangeError, CharacterCultivationError, StateConflictError) as exc:
            raise YixingError(str(exc)) from exc
        except IdempotencyConflictError as exc:
            raise YixingConflictError("请求编号已经用于其他操作") from exc
        return _result(payload, receipt.replayed)

    async def _authorize(self, user_id: str) -> None:
        result = await self._player_state.authorize(user_id, self._guard_rule)
        if not result.allowed:
            raise YixingError(result.reason)


def _result(value: Mapping[str, object], replayed: bool) -> YixingResult:
    return YixingResult(str(value.get("人物名称") or ""), str(value.get("原性别") or ""), str(value.get("新性别") or ""), str(value.get("丹药名称") or ""), replayed)


__all__ = ["YixingFeature"]
