'''属性构成审查：`属性构成` 是效果侧的五行，谁配带、键合不合法、权重合不合一，都在这儿守。

为什么需要它：五行契约（`data/战斗/规则/五行.json`）与装载期校验（`game/core/combat/foundation.py`）
只管**契约本身**的形状——字段名、属性集合、相生相克各五条、倍率键齐不齐；
而**实体身上的** `属性构成` 只在构筑装配时校验过键名（`game/core/combat/builds.py`），
「权重合计一百」这条谁也没查。它本来是手工核出来的（全库 600 门功法实测 0 例外），
而给 140 门无相功法补五行的正是最容易破这条的动作——所以把它做成判据。

查三件事：

1. **谁能带**：契约把 `实体属性.来源类别` 钉死为功法/真意/气机/器律，别的实体类别带了就是越界；
2. **键合法**：`属性构成` 的键必须落在 `属性集合`（木火土金水无相）里；
3. **权重合法**：每门权重必须是非负数，且**合计恰好一百**（与根性同为百分制，两边才可比）。

另外把**五行分布**打出来（提示，不算违规）：补五行、调平衡时有用。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查五行构成.py

**退出码：0 = 合规，1 = 有违规。**
'''

from __future__ import annotations

import json
import pathlib
from collections import Counter
from collections.abc import Mapping

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / 'data'
SKIP_PARTS = {'__pycache__'}


def _five_elements() -> Mapping[str, object]:
    path = DATA / '战斗' / '规则' / '五行.json'
    return json.loads(path.read_text(encoding='utf-8'))


def _entities() -> list[tuple[str, str, str, Mapping[str, object]]]:
    '''扫全库，收集带 属性构成 的实体：(文件, 编号, 名称, 构成)。'''

    found: list[tuple[str, str, str, Mapping[str, object]]] = []
    for path in sorted(DATA.rglob('*.json')):
        if SKIP_PARTS & set(path.parts):
            continue
        try:
            body = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        rows = body if isinstance(body, list) else [body]
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            composition = row.get('属性构成')
            if not isinstance(composition, Mapping):
                continue
            found.append((
                str(path.relative_to(ROOT)),
                str(row.get('编号') or ''),
                str(row.get('名称') or ''),
                composition,
            ))
    return found


def check_composition() -> list[str]:
    rules = _five_elements()
    allowed = set(rules.get('属性集合') or ())
    problems: list[str] = []
    for where, code, name, composition in _entities():
        bad = [key for key in composition if key not in allowed]
        if bad:
            problems.append(f'{where} {code} {name}：属性构成里有没登记的五行 ' + '、'.join(bad))
        weights = []
        for key, value in composition.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                problems.append(f'{where} {code} {name}：{key} 的权重不是数字')
                continue
            if float(value) < 0:
                problems.append(f'{where} {code} {name}：{key} 的权重是负数')
            weights.append(float(value))
        total = sum(weights)
        if weights and abs(total - 100.0) > 1e-9:
            problems.append(f'{where} {code} {name}：属性构成权重合计 {total:g}，应为 100')
    return problems


def check_carriers() -> list[str]:
    rules = _five_elements()
    entity_rule = rules.get('实体属性') or {}
    allowed = set(entity_rule.get('来源类别') or ())
    field = str(entity_rule.get('字段') or '属性构成')
    if not allowed:
        return ['五行契约里没有 实体属性.来源类别']
    problems: list[str] = []
    for path in sorted((DATA / '战斗' / '内容' / '功法').iterdir()):
        if not path.is_dir():
            continue
        if path.name in allowed:
            continue
        for child in path.rglob('*.json'):
            text = child.read_text(encoding='utf-8', errors='replace')
            if f'"{field}"' in text:
                problems.append(
                    str(child.relative_to(ROOT)) + '：' + path.name + ' 不在实体属性的来源类别里，却带了 ' + field
                )
    return problems


def report_distribution() -> list[str]:
    counter: Counter[str] = Counter()
    for _where, _code, _name, composition in _entities():
        for key, value in composition.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                counter[str(key)] += float(value)
    total = sum(counter.values()) or 1.0
    order = ('金', '水', '木', '火', '土', '无相')
    parts = [f'{key} {counter[key] / total * 100:.1f}%' for key in order if counter[key]]
    print('  [提示] 全库属性构成分布：' + '、'.join(parts))
    return []


CHECKS = (
    ('属性构成合法', check_composition),
    ('只有四类能带', check_carriers),
    ('分布打出来', report_distribution),
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
        print(f'五行构成审查失败：{failed} 项')
        return 1
    print('五行构成审查通过：键都在登记五行里、权重合计一百、只有四类实体能带')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
