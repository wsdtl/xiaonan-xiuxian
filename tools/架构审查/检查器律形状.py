r"""器律形状审查：按器阶设计强度这件事，能不能被判出来。

器律与功法/真意/气机同属构筑方向，但**强度出口不同**：器阶是它的档位，
`器则.json` 的 `器阶[]` 是那张阶梯表。本判据只管器律自己，不碰那三个方向；
形状类问题（被动槽位、形状漂移）仍归 `检查构筑形状.py`。

七项检查：

1. **阶梯自洽**：`器则.器阶[].阶序` 必须是 1..5 连续、且与数组顺序一致；
2. **没有强度系数**：器律的强度来自**它所在的解锁池**（后天灵宝池的内容本身就更强），设计上刻意
   不引入品阶/倍率——所以 `器律能力倍率` 这个字段**已废除**，任何器律数据里再出现它就是违规（反回归）。
3. **强度出口**：每条器律的展开树里至少一处**量**字段（`SCALABLE`：威力倍率/数值/层数/最高值），
   让内容自己把强度写出来——**不靠系数乘**。不含触发次数、概率、冷却、持续时间：那些是机制参数，
   缩放它们等于改机制。白名单取这四个而不是只取 `威力倍率`：实测只取威力倍率有 60/64 条没有落点，
   而守御/行气/牵制本就不该有伤害，强行加伤害会毁掉定位。
4. **计量闭环**：写入的计量（`方式=增加/设置`）必须在同一门器律里找得到裁定
   （`来源=构筑计量` 的读取，或 `方式=减少/清空`）。这条规则写在
   `game/startup/说明.md` 的构筑章节里，但此前**只有声明没有实现**；
5. **计量不得指向他人**：器律硬边界是「不得越出持有者」，计量的目标必须落在自身；
5b. **主辅口径**：层数只允许操作**本门自己 `添加状态` 出来的状态**（自有蓄势才用计量）。
   实测现状 98 处层数节点全部操作本门自造状态，0 处越界；
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
#: 读取数值 的登记来源，main 里装载（检查函数直接用）。
READ_SOURCES = frozenset()
#: 可缩放字段（白名单）：档位倍率只允许落在这些「量」字段上。
#: 不含 每次行动最多触发 / 概率 / 冷却 / 持续时间 —— 那些是机制参数，缩放它们等于改机制。
SCALABLE = ("威力倍率", "数值", "层数", "最高值")

#: 产出类原子能力：判「同模板换参」时要三样全同才算——事件集合、消费方式、产出集合。
#: 真正的「消费/改动方式」只出现在这些能力上；`计算数值`/`条件执行` 的 `方式` 是算法，不算消费口径。
MUTATORS = ("修改状态层数", "修改构筑计量", "修改行动条", "修改技能冷却", "修改事件标签")
VERBS = (
    "追加攻击", "造成伤害", "触发技能", "恢复资源", "添加状态", "移除状态",
    "修改行动条", "修改技能冷却", "复制技能", "修改事件标签",
)

#: 「消耗全部层数」的合法上界（防手滑）。
STACK_CEILING = 1000


def _read_sources() -> frozenset:
    """读取数值 允许的来源。未登记的名字会被引擎静默取 0，所以必须逐个核对。"""

    data = json.loads((DATA / "战斗" / "定义" / "原子能力.json").read_text(encoding="utf-8"))
    field = (data.get("读取数值") or {}).get("字段") or {}
    options = (field.get("来源") or {}).get("选项") or []
    return frozenset(str(item) for item in options)


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
    for index, row in enumerate(rows):
        if "器律能力倍率" in row:
            problems.append(f"器阶[{index}] 又出现了器律能力倍率——该字段已废除（强度来自解锁池，不靠系数）")
    return problems


def check_rate_scope(laws: dict) -> list[str]:
    problems: list[str] = []
    for num, row in laws.items():
        text = json.dumps(row["原始"], ensure_ascii=False)
        if "器律能力倍率" in text:
            problems.append(f"{num} {row['原始'].get('名称')} 自带器律能力倍率——该字段已废除（强度来自解锁池，不靠系数）")
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
        # 3 强度出口：至少一处「量」字段，器阶倍率才有落点
        if not any(key in node for node in nodes for key in SCALABLE):
            problems.append(f"{label} 没有任何可缩放字段（{SCALABLE}）——档位倍率无处落地")
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
        # 5b 主辅口径：层数只操作本门自己 添加状态 出来的状态（自有蓄势才用计量）
        added = set()
        for node in nodes:
            if node.get("能力") != "添加状态":
                continue
            choice = node.get("状态")
            added.add(str(choice.get("名称")) if isinstance(choice, Mapping) else str(choice))
        for node in nodes:
            if node.get("能力") != "修改状态层数":
                continue
            choice = node.get("状态")
            name = str(choice.get("名称")) if isinstance(choice, Mapping) else str(choice)
            if name not in added:
                problems.append(f"{label} 直接改状态[{name}]的层数——器律只能操作自己添加的状态")
        # 7 读取数值：来源必须登记过（注册表：未登记的名字会被静默取 0）
        for node in nodes:
            if node.get("能力") != "读取数值":
                continue
            source = str(node.get("来源") or "")
            if source not in READ_SOURCES:
                problems.append(f"{label} 读取数值的来源[{source}]不在注册表选项内——引擎会静默取 0")
            elif source == "构筑计量":
                name = str(node.get("计量") or "")
                if not name:
                    problems.append(f"{label} 读取构筑计量但没写计量名（会静默取 0）")
                elif name not in written:
                    # 只认 written：读取本身在闭环检查里算「有裁定」，不能拿它自证存在。
                    problems.append(f"{label} 读取了本门没写过的计量[{name}]")
            elif source == "状态层数":
                name = str(node.get("状态") or node.get("名称") or "")
                if name and name not in added:
                    problems.append(f"{label} 读取了本门没添加过的状态[{name}]的层数")
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


def check_similar(laws: dict) -> list[str]:
    """同一用途内，事件集合 + 消费方式 + 产出集合三样全同，就是同一模板换参数。

    只比事件集合会误伤：共用「造成伤害后」的两条仍可因消费方式与产出不同而各成一派
    （例如蓄锋引爆 / 冷却窃取 / 层数不清零）。三样全同才是用户说的「换名换参」。
    """

    import collections

    groups: dict[tuple, list] = collections.defaultdict(list)
    for num, row in sorted(laws.items()):
        nodes = _nodes(row["展开"])
        events = tuple(sorted({str(n.get("事件")) for n in nodes if n.get("能力") == "监听事件"}))
        ways = tuple(sorted({str(n.get("方式")) for n in nodes if n.get("能力") in MUTATORS and n.get("方式") is not None}))
        verbs = tuple(sorted({str(n.get("能力")) for n in nodes if n.get("能力") in VERBS}))
        groups[(row["用途"], events, ways, verbs)].append(f"{row['原始'].get('名称')}({num})")
    problems: list[str] = []
    for (use, events, ways, verbs), members in groups.items():
        if len(members) > 1:
            problems.append(
                f"{use} 内同一模板换参数：{'、'.join(sorted(members))}"
                f"（事件 {'+'.join(events) or '无'} · 方式 {'+'.join(ways) or '无'} · 产出 {'+'.join(verbs) or '无'}）"
            )
    return problems


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
    use_of: dict[str, str] = {}
    for file in sorted(LAW_DIR.glob("器律-*.json")):
        for entry in json.loads(file.read_text(encoding="utf-8")):
            raw[str(entry["编号"])] = entry
            use_of[str(entry["编号"])] = file.stem[3:]
    services = app.build_game_services()
    try:
        data = services.core.data
        laws = {}
        for num, entry in raw.items():
            tree = _plain(data.entity("器律", num))
            laws[num] = {"原始": entry, "展开": tree, "用途": use_of[num]}
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
    global READ_SOURCES
    READ_SOURCES = _read_sources()
    problems = check_ladder()
    print("  [" + ("干净" if not problems else str(len(problems)) + " 处") + "] 器阶阶梯")
    for item in problems[:6]:
        print("     " + item)
    laws = load_laws()
    scope = check_rate_scope(laws)
    print("  [" + ("干净" if not scope else str(len(scope)) + " 处") + "] 倍率只属于档位")
    law_problems, _, _ = check_law(laws)
    distinct = check_distinct(laws)
    similar = check_similar(laws)
    print("  [" + ("干净" if not law_problems else str(len(law_problems)) + " 处") + "] 强度出口 / 计量闭环 / 不越界 / 层数")
    for item in law_problems[:6]:
        print("     " + item)
    print("  [" + ("干净" if not distinct else str(len(distinct)) + " 处") + "] 两两不等（" + str(len(laws)) + " 条）")
    print("  [" + ("干净" if not similar else str(len(similar)) + " 处") + "] 同模板换参数")
    for item in distinct[:4]:
        print("     " + item)
    pass
    if similar:
        for item in similar[:6]:
            print("     " + item)
    # 64 条逐条设计已全部完成，同模板换参数不再是「先报不判」——它就是不合格。
    problems += scope + law_problems + distinct + similar
    if problems:
        print(f"器律形状 {len(problems)} 处")
        return 1
    print("器律形状审查通过：阶梯 / 无强度系数 / 量落点 / 计量 / 层数 / 唯一性")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
