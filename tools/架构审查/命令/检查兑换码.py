'''兑换码审查：码本身、发放清单、编号段，以及一条安全规矩。

查八件事（第八件是 2026-10 加随机发放时补的）：

1. **码唯一且干净**：同一批里不许有两个码（比较时统一大写），码只由大写字母与数字组成、长度 3 到 32；
2. **编号在 64 段**：兑换码的编号必须是六位数字、以 64 开头；
3. **每条都有名称与说明**：编号实体一律要这两样（物品目录遍历全体，缺了装载就过不去）；
4. **发放类型在契约里**：类型必须登记在 `玩法/兑换码/定义/发放类型.json`；
5. **必填字段齐、数量合理**：必填字段不为空，单条数量 1 到 1000000，一次发放不超过 20 条；
6. **物品编号真的能进纳戒**：物品编号的前两位必须是「基础物品」那七个子类之一（恢复丹/战丹/突破丹/特殊丹/灵植/灵矿/兽宝）——
   落不进去的，资产核心自己也会拒；
7. **码不许被查询到**：`game/core/item_catalog/service.py` 的 `_ENTITY_FIELDS` 里不许出现兑换码表项，
   否则码会被物品查询列出来。这条写在判据里，是防以后有人顺手加。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查兑换码.py

**退出码：0 = 合规，1 = 有违规。**
'''

from __future__ import annotations

import json
import pathlib
import re
from collections.abc import Mapping

ROOT = pathlib.Path(__file__).resolve().parents[3]
DATA = ROOT / 'data'
COMPONENT = DATA / '玩法' / '通用' / '兑换码'
#: 纳戒（基础物品）的七个子类；物品编号的前两位必须落在其中之一。
INVENTORY_SUBCATEGORIES = ('恢复丹', '战丹', '突破丹', '特殊丹', '灵植', '灵矿', '兽宝')
MAX_GRANTS = 20
#: 与 `game/features/duihuan/service.py` 的 MAX_QUANTITY 同批：防手滑，不是平衡手段。
MAX_QUANTITY = 1_000_000
CODE_PATTERN = re.compile(r'[A-Z0-9]{3,32}')


def _load(path: pathlib.Path):
    return json.loads(path.read_text(encoding='utf-8'))


def _codes() -> list[Mapping[str, object]]:
    path = COMPONENT / '内容' / '兑换码.json'
    body = _load(path)
    return [row for row in body if isinstance(row, Mapping)]


def _types() -> dict[str, Mapping[str, object]]:
    rows = _load(COMPONENT / '定义' / '发放类型.json')
    return {str(row.get('类型')): row for row in rows if isinstance(row, Mapping)}


def _inventory_prefixes() -> set[str]:
    body = _load(DATA / '基础' / '定义' / '编号.json')
    out = set()
    # 号段表两个字段的用法并不一致：丹药那几行把子类写在「主体」上（主体=恢复丹、类别=丹药），
    # 而灵植/灵矿/兽宝写在「类别」上（主体=基础物品、类别=灵植）。所以两个字段都要看一遍。
    for row in body['编号前缀']:
        if not isinstance(row, Mapping):
            continue
        if str(row.get('主体')) in INVENTORY_SUBCATEGORIES or str(row.get('类别')) in INVENTORY_SUBCATEGORIES:
            out.add(str(row.get('前缀')))
    return out


def check_codes() -> list[str]:
    problems: list[str] = []
    seen: dict[str, str] = {}
    for row in _codes():
        code_id = str(row.get('编号') or '')
        code = str(row.get('码') or '').strip().upper()
        if len(code_id) != 6 or not code_id.isdigit() or not code_id.startswith('64'):
            problems.append(f'{code_id or "（无编号）"}：编号必须是六位数字且以 64 开头')
        if not CODE_PATTERN.fullmatch(code):
            problems.append(f'{code_id}：码「{code}」只能由大写字母与数字组成，长度 3 到 32')
        if code in seen:
            problems.append(f'{code_id} 与 {seen[code]} 的码重复：{code}')
        seen[code] = code_id
        for field in ('名称', '说明'):
            if not str(row.get(field) or '').strip():
                problems.append(f'{code_id}：缺{field}（编号实体一律要这两样）')
        limit = row.get('每人限次', 1)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            problems.append(f'{code_id}：每人限次必须是不小于 1 的整数')
    return problems


def check_grants() -> list[str]:
    problems: list[str] = []
    types = _types()
    prefixes = _inventory_prefixes()
    if not types:
        return ['发放类型契约是空的']
    if not prefixes:
        return ['编号表里找不到基础物品的号段']
    for row in _codes():
        code_id = str(row.get('编号') or '')
        grants = row.get('发放')
        if not isinstance(grants, list) or not grants:
            problems.append(f'{code_id}：发放是空的')
            continue
        if len(grants) > MAX_GRANTS:
            problems.append(f'{code_id}：一次发放 {len(grants)} 条，超过 {MAX_GRANTS} 条')
        for index, item in enumerate(grants, start=1):
            if not isinstance(item, Mapping):
                problems.append(f'{code_id} 第 {index} 条：发放项必须是对象')
                continue
            kind = str(item.get('类型') or '')
            rule = types.get(kind)
            if rule is None:
                problems.append(f'{code_id} 第 {index} 条：发放类型「{kind}」没在契约里')
                continue
            for field in rule.get('必填字段') or ():
                if item.get(field) in (None, ''):
                    problems.append(f'{code_id} 第 {index} 条：{kind} 缺必填字段「{field}」')
            quantity = item.get('数量')
            if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= MAX_QUANTITY:
                problems.append(f'{code_id} 第 {index} 条：数量必须是 1 到 {MAX_QUANTITY} 的整数')
            if kind == '物品':
                item_id = str(item.get('编号') or '')
                if item_id[:2] not in prefixes:
                    problems.append(f'{code_id} 第 {index} 条：物品编号 {item_id} 不在纳戒的七个子类里（发不进纳戒）')
    return problems


def check_not_browsable() -> list[str]:
    path = ROOT / 'game' / 'core' / 'item_catalog' / 'service.py'
    text = path.read_text(encoding='utf-8')
    if '兑换码' in text:
        return ['物品目录的字段表里出现了兑换码：码会被物品查询列出来，必须删掉']
    return []



def check_random_grants() -> list[str]:
    '''随机发放的候选池要查实：文件找得到、抽得满、候选都能进纳戒。

    `候选文件` 是兑换码侧的名字——加载器只把**以「池」结尾**的键当资源池引用，
    用「池」就得在全局资源池字段表里登记实体类别，而随机候选允许跨类别。
    '''

    problems: list[str] = []
    prefixes = _inventory_prefixes()
    for row in _codes():
        code_id = str(row.get('编号') or '')
        for index, item in enumerate(row.get('发放') or (), start=1):
            if not isinstance(item, Mapping) or str(item.get('类型') or '') != '随机物品':
                continue
            raw = item.get('候选文件')
            names = [raw] if isinstance(raw, str) else list(raw or ())
            names = [str(name).strip() for name in names]
            if not names or any(not name for name in names):
                problems.append(f'{code_id} 第 {index} 条：随机物品的候选文件必须是非空文件名或文件名列表')
                continue
            seen: set[str] = set()
            for name in names:
                found = sorted(DATA.rglob(f'{name}.json'))
                if len(found) != 1:
                    problems.append(f'{code_id} 第 {index} 条：候选文件 {name} 在 data 下匹配到 {len(found)} 份')
                    continue
                body = _load(found[0])
                for entity in body if isinstance(body, list) else [body]:
                    if not isinstance(entity, Mapping):
                        continue
                    entity_id = str(entity.get('编号') or '')
                    if entity_id[:2] not in prefixes:
                        problems.append(
                            f'{code_id} 第 {index} 条：候选文件 {name} 里的 {entity_id} 不在纳戒七个子类里'
                        )
                    seen.add(entity_id)
            quantity = item.get('数量')
            if isinstance(quantity, int) and not isinstance(quantity, bool) and quantity > len(seen):
                problems.append(
                    f'{code_id} 第 {index} 条：候选池只有 {len(seen)} 件，抽不满 {quantity} 件（去重抽取）'
                )
    return problems

CHECKS = (
    ('码本身与编号', check_codes),
    ('发放清单', check_grants),
    ('随机发放的候选池', check_random_grants),
    ('码不许被查询到', check_not_browsable),
)


def main() -> int:
    failed = 0
    for label, check in CHECKS:
        problems = check()
        if problems:
            failed += 1
            print(f'  [{len(problems)} 处] {label}')
            for line in problems[:8]:
                print('        ' + line)
        else:
            print(f'  [干净] {label}')
    if failed:
        print(f'兑换码审查失败：{failed} 项')
        return 1
    print('兑换码审查通过：码唯一干净、发放只进纳戒与灵石、随机池抽得满、码不可被查询')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
