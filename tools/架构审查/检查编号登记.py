"""编号登记审查：6 位编号的分配是否守规矩。

依据 data/基础/定义/编号.json：编号 6 位 = 2 位前缀 + 4 位流水、字符串存储；它承担
「数据库主键」「存档实体引用」「JSON 实体引用」，所以必须满足三件事：

1. 号段表自洽：前缀是 2 位数字、互不重复、主体与类别都有话；
2. 实体编号合法：每个带编号的实体数据里的编号都是 6 位数字，且前缀在号段表登记过；
3. 全局唯一：同一个编号不许出现在两个地方。

展示层的「按钮」编号**不算实体编号**——那是界面元素 id（按钮 .json 里的 1、2、3…），
所以扫描时排除 展示/ 目录。这条区分写在 _输出/ID化整理.md 里，这里是它的可执行版本。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查编号登记.py

**退出码：0 = 合规，1 = 有编号违规。**
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA = ROOT / "data"
REGISTRY = DATA / "基础" / "定义" / "编号.json"
#: 6 位编号：2 位前缀 + 4 位流水。
NUMBER = re.compile(r"\d{6}")
PREFIX = re.compile(r"\d{2}")
#: 品级有自己的编号规则（号段表里写明的「品级编号规则」），位数从那里读。
GRADE_FILE = "基础/定义/品级.json"

#: 展示层与界面文本不进实体扫描。
SKIP_PARTS = ("展示",)


def _definitions(node: object, sink: list[dict]) -> None:
    """只把顶层记录当定义。

    实体文件里既有定义也有引用：道侣文件顶层的 5 个道侣是定义（自己的 50xxxx），
    它们携带的丹药与材料是**引用**（嵌套出现的 10xxxx / 20xxxx）。
    拿递归结果查唯一性会把引用算成重复，所以这里只取顶层。
    """

    if isinstance(node, list):
        rows = node
    elif isinstance(node, dict):
        rows = [node] if "编号" in node else list(node.values())
    else:
        return
    for row in rows:
        if isinstance(row, dict) and "编号" in row:
            sink.append(row)

def check_registry() -> tuple[list[str], dict[str, dict]]:
    """号段表自洽；顺带把前缀表取出来给别的检查用。"""

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    rows = registry.get("编号前缀") or []
    problems: list[str] = []
    by_prefix: dict[str, dict] = {}
    for index, row in enumerate(rows):
        prefix = str(row.get("前缀") or "")
        if not PREFIX.fullmatch(prefix):
            problems.append(f"第 {index} 条前缀不是两位数字：{prefix or '<空>'}")
            continue
        if prefix in by_prefix:
            problems.append(f"前缀重复登记：{prefix}")
        if not str(row.get("主体") or "").strip() or not str(row.get("类别") or "").strip():
            problems.append(f"前缀 {prefix} 的主体或类别是空的")
        by_prefix[prefix] = row
    grade = registry.get("品级编号规则") or {}
    try:
        grade_digits = int(grade.get("位数") or 0)
    except (TypeError, ValueError):
        grade_digits = 0
    if grade_digits <= 0:
        problems.append("号段表没有可用的品级编号位数")
    return problems, by_prefix, grade_digits


def check_entities(
    by_prefix: dict[str, dict], grade_digits: int
) -> tuple[list[str], Counter, Counter]:
    """实体编号：合法、前缀登记过、全局唯一。"""

    problems: list[str] = []
    per_prefix: Counter = Counter()
    per_file: Counter = Counter()
    seen: dict[str, str] = {}
    for file in sorted(DATA.rglob("*.json")):
        rel = file.relative_to(DATA)
        if any(part in SKIP_PARTS for part in rel.parts):
            continue
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except Exception:
            continue
        sink: list[dict] = []
        _definitions(data, sink)
        for row in sink:
            number = str(row.get("编号") or "")
            where = str(rel).replace(chr(92), "/")
            if where == GRADE_FILE:
                if len(number) != grade_digits or not number.isdigit():
                    problems.append(f"{where}：品级编号不是 {grade_digits} 位数字：{number or '<空>'}")
                continue
            if not NUMBER.fullmatch(number):
                problems.append(f"{where}：编号不是 6 位数字：{number or '<空>'}")
                continue
            prefix = number[:2]
            if prefix not in by_prefix:
                problems.append(f"{where}：编号 {number} 的前缀 {prefix} 没在号段表登记")
            if number in seen and seen[number] != where:
                problems.append(f"编号 {number} 同时出现在 {seen[number]} 与 {where}")
            seen[number] = where
            per_prefix[prefix] += 1
            per_file[where] += 1
    return problems, per_prefix, per_file


def main() -> int:
    problems, by_prefix, grade_digits = check_registry()
    print(f"  [{'干净' if not problems else str(len(problems)) + ' 处'}] 号段表（{len(by_prefix)} 段）")
    for item in problems[:5]:
        print("     " + item)
    entity_problems, per_prefix, per_file = check_entities(by_prefix, grade_digits)
    problems.extend(entity_problems)
    print(f"  [{'干净' if not entity_problems else str(len(entity_problems)) + ' 处'}] 实体编号")
    for item in entity_problems[:5]:
        print("     " + item)
    for prefix in sorted(per_prefix):
        row = by_prefix.get(prefix, {})
        print(f"     {prefix}  {str(row.get('主体') or '?'):<8}{str(row.get('类别') or '?'):<10}{per_prefix[prefix]:>5} 条")
    if problems:
        print(f"编号登记 {len(problems)} 处")
        return 1
    print(f"编号登记审查通过：{len(by_prefix)} 段、{sum(per_prefix.values())} 条实体编号，全局唯一")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
