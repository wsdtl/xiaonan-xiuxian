r"""器律形状审查：按器阶设计强度这件事，能不能被判出来。

器律与功法/真意/气机同属构筑方向，但**强度出口不同**：器阶是它的档位，
`器则.json` 的 `器阶[]` 是那张阶梯表。本判据只管器律自己，不碰那三个方向；
形状类问题（被动槽位、形状漂移）仍归 `检查构筑形状.py`。

七项检查：

1. **阶梯自洽**：`器则.器阶[].阶序` 必须是 1..5 连续、且与数组顺序一致；
2. **倍率单调**：`器律能力倍率` 随阶序严格递增，且只允许出现在 `器则.json` 的 `器阶[]` 里
   （器律实体自带倍率即越界——倍率是档位事实，不是内容事实，同品级那条禁令）；
3. **强度出口**：每条器律的展开树里至少一处可缩放字段（`威力倍率`）。
   **当前先报不判**：现状 64 条里只有 4 条有，逐条重新设计完成后转硬；
4. **计量闭环**：写入的计量（`方式=增加/设置`）必须在同一门器律里找得到裁定
   （`来源=构筑计量` 的读取，或 `方式=减少/清空`）。这条规则写在
   `game/startup/说明.md` 的构筑章节里，但此前**只有声明没有实现**；
5. **计量不得指向他人**：器律硬边界是「不得越出持有者」，计量的目标必须落在自身；
6. **层数语义一致**：`层数 ≥ 状态层数上限` 是渲染器承认的「消耗全部」写法
   （`card_text.py` 的 `_consumes_all`），但必须配 `不足时是否失败=false` 且 `方式=减少`；
   另外 `层数` 不得超过 1000（防手滑写成 10000）；
7. **两两不等**：去掉名称后按展开树签名比对，任意两条不许等价。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查器律形状.py

**退出码：0 = 合规，1 = 有器律缺陷。**
"""

from __future__ import annotations

import json
import pathlib
import sys
from collections.abc import Mapping, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA = ROOT / "data"
RECIPE = DATA / "物品" / "炼器" / "规则" / "器则.json"
LAW_DIR = DATA / "物品" / "炼器" / "内容"
TIERS = ("凡器", "灵器", "法器", "法宝", "后天灵宝")
#: 「消耗全部层数」的合法上界（防手滑）。
STACK_CEILING = 1000


def _recipes() -> list[dict]:
    data = json.loads(RECIPE.read_text(encoding="utf-8"))
    rows = data.get("器阶")
    if not isinstance(rows, list):
        raise SystemExit("器则.json 缺少 器阶[]")
    return rows


def check_ladder() -> list[str]:
    rows = _recipes()
    problems: list[str] = []
    if [str(r.get("名称")) for r in rows] != list(TIERS):
        problems.append("器阶顺序不是 凡器..后天灵宝：" + str([r.get("名称") for r in rows]))
    orders = [r.get("阶序") for r in rows]
    if orders != list(range(1, len(rows) + 1)):
        problems.append("阶序必须是 1..N 且与数组顺序一致，实际 " + str(orders))
    rates = [r.get("器律能力倍率") for r in rows]
    for index, rate in enumerate(rates):
        if not isinstance(rate, (int, float)) or isinstance(rate, bool):
            problems.append(f"器阶[{index}] 的器律能力倍率不是数字：{rate}")
    numeric = [float(r) for r in rates if isinstance(r, (int, float)) and not isinstance(r, bool)]
    if len(numeric) == len(rates) and any(numeric[i] >= numeric[i + 1] for i in range(len(numeric) - 1)):
        problems.append("器律能力倍率不是严格递增：" + str(numeric))
    return problems


def check_rate_scope(laws: dict) -> list[str]:
    problems: list[str] = []
    for num, row in laws.items():
        text = json.dumps(row["原始"], ensure_ascii=False)
        if "器律能力倍率" in text:
            problems.append(f"{num} {row['原始'].get('名称')} 自带器律能力倍率——倍率属于档位，不属于内容")
    return problems


def _walk(node, sink):
    if isinstance(node, Mapping):
        sink.append(node)
        for value in node.values():
            _walk(value, sink)
    elif isinstance(node, Sequence) and not isinstance(node, str):
        for value in node:
            _walk(value, sink)


def _nodes(tree) -> list[Mapping]:
    sink: list[Mapping] = []
    _walk(tree.get("能力"), sink)
    return sink


def _counter_name(node: Mapping) -> str:
    value = node.get("计量")
    return str(value).strip() if isinstance(value, str) else ""


def check_law(laws: dict) -> tuple[list[str], list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []
    names: list[str] = []
    limits = {str(row.get("名称")): row.get("层数上限") for row in json.loads((DATA / "战斗" / "定义" / "状态.json").read_text(encoding="utf-8"))} if (DATA / "战斗" / "定义" / "状态.json").is_file() else {}
    for num, row in sorted(laws.items()):
        label = str(row["原始"].get("名称"))
        nodes = _nodes(row["展开"])
        # 3 强度出口（先报不判）
        if not any("威力倍率" in node for node in nodes):
            warnings.append(f"{label} 没有可缩放字段（威力倍率）——逐条设计完成后必须补")
        # 4 计量闭环
        written: set[str] = set()
        settled: set[str] = set()
        for node in nodes:
            if node.get("能力") == "修改构筑计量":
                name = _counter_name(node)
                way = str(node.get("方式") or "增加")
                if way in ("增加", "设置"):
                    written.add(name)
                else:
                    settled.add(name)
            if str(node.get("来源")) == "构筑计量":
                settled.add(_counter_name(node) or str(node.get("计量") or ""))
        for name in sorted(n for n in written if n and n not in settled):
            problems.append(f"{label} 写了计量[{name}]但同一门里没有裁定（闭环缺口）")
        # 5 计量不得指向他人
        for node in nodes:
            if node.get("能力") != "修改构筑计量":
                continue
            target = node.get("目标")
            scope = str(target.get("范围")) if isinstance(target, Mapping) else ""
            if scope and scope != "自身":
                problems.append(f"{label} 的计量[{_counter_name(node)}]指向 {scope}——器律不得越出持有者")
        # 6 层数语义
        for node in nodes:
            if node.get("能力") != "修改状态层数":
                continue
            stacks = node.get("层数")
            if not isinstance(stacks, (int, float)) or isinstance(stacks, bool):
                continue
            if float(stacks) > STACK_CEILING:
                problems.append(f"{label} 的层数={stacks} 超过 {STACK_CEILING}，像手滑")
            if float(stacks) >= 100:
                if str(node.get("方式") or "增加") != "减少":
                    problems.append(f"{label} 用大层数({stacks})表示「全部」，但方式不是减少")
                if node.get("不足时是否失败") is not False:
                    problems.append(f"{label} 用大层数({stacks})表示「全部」，但 不足时是否失败 不是 false")
    return problems, warnings, names


def check_distinct(laws: dict) -> list[str]:
    import collections

    def strip(node):
        if isinstance(node, Mapping):
            return {k: strip(v) for k, v in node.items() if k not in ("名称", "名称2", "说明")}
        if isinstance(node, Sequence) and not isinstance(node, str):
            return [strip(v) for v in node]
        return node

    groups = collections.defaultdict(list)
    for num, row in laws.items():
        groups[json.dumps(strip(row["展开"].get("能力")), ensure_ascii=False, sort_keys=True)].append
        groups[json.dumps(strip(row["展开"].get("能力")), ensure_ascii=False, sort_keys=True)].append(
            str(row["原始"].get("名称"))
        )
    problems: list[str] = []
    for key, names in groups.items():
        if len(names) > 1:
            problems.append("等价器律：" + "、".join(sorted(names)))
    return problems


def load_laws() -> dict:
    import game.app as app

    raw = {}
    for file in sorted(LAW_DIR.glob("器律-*.json")):
        for entry in json.loads(file.read_text(encoding="utf-8")):
            raw[str(entry["编号"])] = entry
    services = app.build_game_services()
    try:
        data = services.core.data
        laws = {}
        for num, entry in raw.items():
            tree = _plain(data.entity("器律", num))
            laws[num] = {"原始": entry, "展开": tree}
        return laws
    finally:
        services.core.database.close()


def _plain(node):
    if isinstance(node, Mapping):
        return {str(k): _plain(v) for k, v in node.items()}
    if isinstance(node, Sequence) and not isinstance(node, str):
        return [_plain(v) for v in node]
    return node


def main() -> int:
    problems = check_ladder()
    print("  [" + ("干净" if not problems else str(len(problems)) + " 处") + "] 器阶阶梯")
    for item in problems[:6]:
        print("     " + item)
    laws = load_laws()
    scope = check_rate_scope(laws)
    print("  [" + ("干净" if not scope else str(len(scope)) + " 处") + "] 倍率只属于档位")
    law_problems, warnings, _ = check_law(laws)
    distinct = check_distinct(laws)
    print("  [" + ("干净" if not law_problems else str(len(law_problems)) + " 处") + "] 计量闭环 / 不越界 / 层数语义")
    for item in law_problems[:6]:
        print("     " + item)
    print("  [" + ("干净" if not distinct else str(len(distinct)) + " 处") + "] 两两不等（" + str(len(laws)) + " 条）")
    for item in distinct[:4]:
        print("     " + item)
    if warnings:
        print("  [先报不判] 强度出口：" + str(len(warnings)) + " 条待补（逐条设计完成后转硬）")
    problems += scope + law_problems + distinct
    if problems:
        print(f"器律形状 {len(problems)} 处")
        return 1
    print("器律形状审查通过：阶梯 / 倍率归属 / 计量 / 层数 / 唯一性")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
