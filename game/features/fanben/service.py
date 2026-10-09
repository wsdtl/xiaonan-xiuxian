"""返本还元：在太素坊服用返本还元丹，把人物换成地点配置里指定的种族。

**为什么走地点而不是服丹**：特殊丹一律绑定对应地点使用（委托方口径，也是既有约定）——
太素坊的说明就是「两仪泉可引易形丹药力重塑玩家形体」，「易形」管性别、「返本」管种族，
两者同属「重塑形体」，所以共用一处地点、各自一个功能。绑定写在 `data/世界/.../太素坊.json` 的
`功能配置.返本.丹药` 里，本服务只读它，不硬编码编号。
"""

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

from .contracts import FanbenConflictError, FanbenError, FanbenResult

FUNCTION = "化形"


class FanbenFeature:
    def __init__(
        self,
        data: JsonDataService,
        medicine: MedicineService,
        character: CharacterService,
        asset: AssetService,
        player_state: PlayerStateService,
        location: LocationService,
        world: WorldService,
        database: DatabaseService,
    ) -> None:
        self._data, self._medicine, self._character, self._asset = data, medicine, character, asset
        self._player_state, self._location, self._world, self._database = player_state, location, world, database
        self._copy: Mapping[str, object] | None = None
        self._medicine_id = ""
        self._candidates: tuple[str, ...] = ()
        self._medicine_name = ""
        self._guard_rule = ""

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("返本玩法已经初始化")
        rule = self._world.feature_config(FUNCTION)
        self._medicine_id = _text(rule.get("丹药"), "返本.丹药")
        # 候选来自登记表（与「易形」的性别取值同构，只是这里整张表都可选）。
        source = _text(rule.get("候选来源"), "化形.候选来源")
        if source != "种族登记表":
            raise JsonDataError(f"化形.候选来源 只支持「种族登记表」：{source}")
        self._candidates = tuple(sorted(self._character.races()))
        # 丹名从数据读，别在代码里硬编码——改名时这里要跟着走才对。
        self._medicine_name = str(self._data.entity("丹药", self._medicine_id).get("名称") or "换种族丹")
        self._guard_rule = _text(rule.get("状态守卫"), "返本.状态守卫")
        copy = self._data.dataset("化形展示").get("文本")
        if not isinstance(copy, Mapping):
            raise JsonDataError("返本展示缺少文本.json")
        self._copy = copy

    def copy(self, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
        if self._copy is None:
            raise RuntimeError("返本玩法尚未初始化")
        group = self._copy.get(section)
        value = group.get(key) if isinstance(group, Mapping) else None
        if not isinstance(value, str):
            raise JsonDataError(f"返本展示缺少文本：{section}.{key}")
        return value.format_map(values or {})

    async def change(self, user_id: str, request_id: str, race: str) -> FanbenResult:
        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != "返本还元":
                raise FanbenConflictError("请求编号已经用于其他操作")
            return _result(committed.payload, True)
        await self._authorize(user_id)
        try:
            current = await self._location.current(user_id)
            place = self._world.locate(LocationQuery(xy=current.xy))
            if FUNCTION not in place.available_functions:
                raise FanbenError(f"只有身在太素坊才能使用{self._medicine_name}")
            profile = await self._character.profile(user_id)
            wanted = str(race or "").strip()
            if wanted not in self._candidates:
                raise FanbenError(f"没有这一族：{wanted or '（空）'}")
            plan = await self._character.plan_identity_change(user_id, race=wanted)
            stacks = await self._asset.inventory_stacks(user_id, self._medicine_id)
            if not stacks:
                raise FanbenError(f"纳戒中没有{self._medicine_name}")
            stack = min(stacks, key=lambda value: value.grade.order)
            inventory = await self._asset.plan_inventory_changes(
                user_id, (InventoryAdjustment(self._medicine_id, stack.grade.grade_id, -1),)
            )
            payload = {
                "人物名称": profile.name,
                "原种族": plan.before_race,
                "新种族": plan.after_race,
                "丹药名称": self._medicine_name,
            }
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id, request_id, "返本还元", inventory.operations + (plan.mutation,), payload
                )
            )
        except (InventoryChangeError, CharacterCultivationError, StateConflictError) as exc:
            raise FanbenError(str(exc)) from exc
        except IdempotencyConflictError as exc:
            raise FanbenConflictError("请求编号已经用于其他操作") from exc
        return _result(payload, receipt.replayed)

    async def _authorize(self, user_id: str) -> None:
        result = await self._player_state.authorize(user_id, self._guard_rule)
        if not result.allowed:
            raise FanbenError(result.reason)


def _result(value: Mapping[str, object], replayed: bool) -> FanbenResult:
    return FanbenResult(
        str(value.get("人物名称") or ""),
        str(value.get("原种族") or ""),
        str(value.get("新种族") or ""),
        str(value.get("丹药名称") or ""),
        replayed,
    )


__all__ = ["FanbenFeature"]
