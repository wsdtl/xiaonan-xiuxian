'''兑换码：玩家报一个码，按数据里的发放清单交货，一次兑换一笔事务。

**发放边界**（委托方拍板）：只发**纳戒物品**与**灵石**。道藏（功法）、修行资粮（真意/气机）、
器藏（器律）、阵藏（阵法）、所学（丹药的识得）、先天灵宝一律不发——它们各在自己的取得与消耗链上，
塞进去会破坏闭环。特殊丹**可以发**：它被约束的是「使用」（要人在归元观/太素坊），不是「拥有」。

**两条不许含糊的口径**：
1. **每人限次落在人物状态里**（「已兑换码」），不靠请求编号——请求编号管的是同一条请求重放，
   换一条请求就能再兑一次，那是两回事。
2. **查不到与已兑换回同一句**（「码无效或已使用」），并且码表不进物品目录的字段表，
   否则码能被任何人通过查询看到。

灵石与「已兑换码」同在一个地址（character/main），所以由人物核心**合成一份变更**；
纳戒是另一个地址，可以拼在同一条事务里。
'''

from __future__ import annotations

import re
from collections.abc import Mapping

from game.core.asset import AssetService, InventoryAdjustment, InventoryChangeError
from game.core.character import CharacterCultivationError, CharacterService
from game.core.data import JsonDataError, JsonDataService
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    StateConflictError,
    TransactionCommand,
)

from .contracts import DuihuanConflictError, DuihuanError, DuihuanResult

BUSINESS = '兑换码'
CODE_PATTERN = re.compile(r'[A-Z0-9]{3,32}')
MAX_GRANTS = 20
MAX_QUANTITY = 9999


class DuihuanFeature:
    def __init__(
        self,
        data: JsonDataService,
        character: CharacterService,
        asset: AssetService,
        database: DatabaseService,
    ) -> None:
        self._data, self._character, self._asset, self._database = data, character, asset, database
        self._copy: Mapping[str, object] | None = None
        self._types: dict[str, Mapping[str, object]] = {}

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError('兑换码玩法已经初始化')
        rules = self._data.dataset('兑换码发放类型')
        rows = rules if isinstance(rules, (list, tuple)) else rules.get('发放类型')
        for row in rows or ():
            if not isinstance(row, Mapping):
                continue
            name = str(row.get('类型') or '').strip()
            if not name:
                raise JsonDataError('兑换码发放类型缺名字')
            self._types[name] = row
        if not self._types:
            raise JsonDataError('兑换码发放类型是空的')
        copy = self._data.dataset('兑换码展示').get('文本')
        if not isinstance(copy, Mapping):
            raise JsonDataError('兑换码展示缺少文本.json')
        self._copy = copy

    def copy(self, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
        if self._copy is None:
            raise RuntimeError('兑换码玩法尚未初始化')
        group = self._copy.get(section)
        value = group.get(key) if isinstance(group, Mapping) else None
        if not isinstance(value, str):
            raise JsonDataError(f'兑换码展示缺少文本：{section}.{key}')
        return value.format_map(values or {})

    async def redeem(self, user_id: str, request_id: str, raw: str) -> DuihuanResult:
        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != BUSINESS:
                raise DuihuanConflictError('请求编号已经用于其他操作')
            return _result(committed.payload, True)
        code = ' '.join(str(raw or '').split()).upper()
        if not CODE_PATTERN.fullmatch(code):
            raise DuihuanError(self.copy('错误', '格式'))
        row = self._find(code)
        if row is None:
            # 查不到与已兑换回同一句：不给出「这个码存在但用过了」这种可探测的差别。
            raise DuihuanError(self.copy('错误', '无效'))
        code_id = str(row.get('编号') or '')
        limit = row.get('每人限次') or 1
        grants = self._grants(row)
        stones = sum(quantity for kind, _i, _g, quantity in grants if kind == '灵石')
        try:
            plan = await self._character.plan_code_redemption(
                user_id, code_id=code_id, limit=int(limit), spirit_stones=stones
            )
            adjustments = tuple(
                InventoryAdjustment(item_id, grade_id, quantity)
                for kind, item_id, grade_id, quantity in grants
                if kind == '物品'
            )
            inventory = (
                await self._asset.plan_inventory_changes(user_id, adjustments)
                if adjustments
                else None
            )
            operations = (inventory.operations if inventory else ()) + (plan.operation,)
            payload = {
                '码': code,
                '兑换码': code_id,
                '名称': str(row.get('名称') or ''),
                '发放': '、'.join(_grant_text(kind, quantity) for kind, _i, _g, quantity in grants),
            }
            receipt = await self._database.commit(
                TransactionCommand(user_id, request_id, BUSINESS, operations, payload)
            )
        except (InventoryChangeError, CharacterCultivationError, StateConflictError) as exc:
            raise DuihuanError(self.copy('错误', '交割', {'原因': str(exc)})) from exc
        except IdempotencyConflictError as exc:
            raise DuihuanConflictError('请求编号已经用于其他操作') from exc
        return _result(payload, receipt.replayed)

    def _find(self, code: str) -> Mapping[str, object] | None:
        for _code_id, row in sorted(self._data.entities('兑换码').items()):
            if str(row.get('码') or '').strip().upper() == code:
                return row
        return None

    def _grants(self, row: Mapping[str, object]) -> list[tuple[str, str, str, int]]:
        raw = row.get('发放')
        if not isinstance(raw, (list, tuple)) or not raw:
            raise JsonDataError(f"兑换码 {row.get('编号')} 的发放是空的")
        if len(raw) > MAX_GRANTS:
            raise JsonDataError(f"兑换码 {row.get('编号')} 一次发放超过 {MAX_GRANTS} 条")
        lowest = self._asset.grades()[0].grade_id
        out: list[tuple[str, str, str, int]] = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise JsonDataError(f"兑换码 {row.get('编号')} 的发放项必须是对象")
            kind = str(item.get('类型') or '')
            rule = self._types.get(kind)
            if rule is None:
                raise JsonDataError(f'发放类型没有登记：{kind}')
            for field in rule.get('必填字段') or ():
                if item.get(field) in (None, ''):
                    raise JsonDataError(f'发放 {kind} 缺必填字段：{field}')
            quantity = item.get('数量')
            if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= MAX_QUANTITY:
                raise JsonDataError(f'发放数量必须是 1 到 {MAX_QUANTITY} 的整数')
            if kind == '灵石':
                out.append((kind, '', '', quantity))
            else:
                out.append((kind, str(item.get('编号') or ''), str(item.get('品级') or lowest), quantity))
        return out


def _grant_text(kind: str, quantity: int) -> str:
    return f'{kind}×{quantity}' if kind == '灵石' else f'物品×{quantity}'


def _result(value: Mapping[str, object], replayed: bool) -> DuihuanResult:
    return DuihuanResult(
        str(value.get('码') or ''),
        str(value.get('兑换码') or ''),
        str(value.get('名称') or ''),
        str(value.get('发放') or ''),
        replayed,
    )


__all__ = ['DuihuanFeature']
