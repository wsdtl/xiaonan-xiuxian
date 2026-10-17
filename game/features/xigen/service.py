'''洗根：在归元观服下灵根重铸丹，把五行根性整体重掷一次。

**为什么走地点而不是服丹**：特殊丹一律绑定对应地点使用（既有约定）。归元观的字面意思就是
「回到根本」，而五行根性正是这个「根」；所以挂在归元观作第二个功能，与太素坊「易形 + 化形」同构。
绑定写在 `data/世界/内容/天衡州/归元观/归元观.json` 的 `功能配置.洗根.丹药` 里，本服务只读它，不硬编码编号。

**随机性口径**：五行根性原本由 `random.Random(f'人物五行:{user_id}')` 定种，同一玩家永远一副。
洗根改用 `f'洗根:{user_id}:{request_id}'` —— 同一条请求重放掷出同一副（事务幂等），换一条请求才是新的一掷。
生成复用 `game.core.combat.generate_five_elements`，与建号同一套规则，产出照样过得了入库校验。
'''

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

from .contracts import XigenConflictError, XigenError, XigenResult

FUNCTION = '洗根'
BUSINESS = '灵根重铸'
ORDER = ('木', '火', '土', '金', '水')


def _format_elements(value: Mapping[str, float]) -> str:
    '''把根性排成人读得懂的一行：数值从大到小，同值按木火土金水的次序。'''

    def rank(item: tuple[str, float]) -> tuple[float, int]:
        element, amount = item
        return (-float(amount), ORDER.index(element) if element in ORDER else 9)

    return ' '.join(f'{element}{float(amount):g}' for element, amount in sorted(value.items(), key=rank))


class XigenFeature:
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
        self._medicine_id = ''
        self._medicine_name = ''
        self._guard_rule = ''

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError('洗根玩法已经初始化')
        rule = self._world.feature_config(FUNCTION)
        self._medicine_id = _text(rule.get('丹药'), '洗根.丹药')
        self._guard_rule = _text(rule.get('状态守卫'), '洗根.状态守卫')
        # 丹名从数据读，别在代码里硬编码——改名时这里要跟着走才对。
        self._medicine_name = str(
            self._data.entity('丹药', self._medicine_id).get('名称') or '灵根重铸丹'
        )
        copy = self._data.dataset('洗根展示').get('洗根')
        if not isinstance(copy, Mapping):
            raise JsonDataError('洗根展示缺少文本.json')
        self._copy = copy

    def copy(self, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
        if self._copy is None:
            raise RuntimeError('洗根玩法尚未初始化')
        group = self._copy.get(section)
        value = group.get(key) if isinstance(group, Mapping) else None
        if not isinstance(value, str):
            raise JsonDataError(f'洗根展示缺少文本：{section}.{key}')
        return value.format_map(values or {})

    async def change(self, user_id: str, request_id: str) -> XigenResult:
        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != BUSINESS:
                raise XigenConflictError('请求编号已经用于其他操作')
            return _result(committed.payload, True)
        await self._authorize(user_id)
        try:
            current = await self._location.current(user_id)
            place = self._world.locate(LocationQuery(xy=current.xy))
            if FUNCTION not in place.available_functions:
                raise XigenError(f'只有身在归元观才能使用{self._medicine_name}')
            profile = await self._character.profile(user_id)
            plan = await self._character.plan_five_elements_change(
                user_id, seed=f'洗根:{user_id}:{request_id}'
            )
            stacks = await self._asset.inventory_stacks(user_id, self._medicine_id)
            if not stacks:
                raise XigenError(f'纳戒中没有{self._medicine_name}')
            stack = min(stacks, key=lambda value: value.grade.order)
            inventory = await self._asset.plan_inventory_changes(
                user_id, (InventoryAdjustment(self._medicine_id, stack.grade.grade_id, -1),)
            )
            payload = {
                '人物名称': profile.name,
                '原根性': _format_elements(plan.before),
                '新根性': _format_elements(plan.after),
                '重掷次数': plan.repeated,
                '丹药名称': self._medicine_name,
            }
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id, request_id, BUSINESS, inventory.operations + (plan.operation,), payload
                )
            )
        except (InventoryChangeError, CharacterCultivationError, StateConflictError) as exc:
            raise XigenError(str(exc)) from exc
        except IdempotencyConflictError as exc:
            raise XigenConflictError('请求编号已经用于其他操作') from exc
        return _result(payload, receipt.replayed)

    async def _authorize(self, user_id: str) -> None:
        result = await self._player_state.authorize(user_id, self._guard_rule)
        if not result.allowed:
            raise XigenError(result.reason)


def _result(value: Mapping[str, object], replayed: bool) -> XigenResult:
    return XigenResult(
        str(value.get('人物名称') or ''),
        str(value.get('原根性') or ''),
        str(value.get('新根性') or ''),
        str(value.get('丹药名称') or ''),
        int(value.get('重掷次数') or 0),
        replayed,
    )


__all__ = ['XigenFeature']
