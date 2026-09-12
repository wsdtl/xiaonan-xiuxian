"""监听顺序盘点：找出「顺序会改变结果」的监听声明。

`优先级` 只决定同一事件内多个监听的先后。它**不是**按数量铺的东西——5152 条监听
里绝大多数（例如 2395 条「行动结束」）只读自己那张卡的构筑计量，而计量全库唯一，
所以和别的卡不冲突，给它们标优先级是装饰。

真正需要声明的是**改写共享量**的监听：同一条事件上，一个监听改写、
另一个读同一个量时，先后才改变结果。共享量指：

    事件数值 / 事件目标 / 事件标签 / 事件存活 / 判定 / 资源 / 行动条 / 冷却
    属性（经状态修饰间接改写）/ 战场规则

非共享量：构筑计量（全库唯一）、保存结果与事实（按卡命名）、大多数状态名。
所以「改写者」的判据是调用了上表相关的原子能力，而不是「有没有写东西」。

    .venv/Scripts/python.exe -X utf8 tools/盘点监听顺序.py
    .venv/Scripts/python.exe -X utf8 tools/盘点监听顺序.py --报告 _监听顺序.txt
"""

from __future__ import annotations

import argparse
import collections
import io
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 改写**本次事件**的能力：同一个事件上，这些和「读本次数值的监听」互斥先后。
EVENT_WRITERS = {
    "修改事件数值": "事件数值",
    "修改事件目标": "事件目标",
    "修改事件标签": "事件标签",
    "取消事件": "事件存活",
    "转化事件": "事件存活",
    "修改判定": "判定",
}

#: 改写**状态修饰**的能力：属性与层数的来源，影响同事件上读属性的监听。
STATE_WRITERS = {
    "添加状态": "状态",
    "移除状态": "状态",
    "增加状态层数": "状态",
    "消耗状态层数": "状态",
    "复制状态": "状态",
    "转移状态": "状态",
}

#: `读取数值.来源` 映射到共享量。**故意不收 `构筑计量` 与 `保存结果`**：
#: 计量全库唯一（3757 处），结果是按卡命名的，两者都不跨卡冲突。
READ_SOURCES = {
    "本次数值": "事件数值",
    "事件事实": "事件数值",
    "自身属性": "属性",
    "目标属性": "属性",
    "状态层数": "状态",
    "战斗记录": "记录",
    "自身当前血气": "资源",
    "目标当前血气": "资源",
    "自身已损失血气": "资源",
    "目标已损失血气": "资源",
    "自身当前精神": "资源",
    "目标当前精神": "资源",
    "目标已损失精神": "资源",
}

#: 组合能力，盘点时要钻进去看。
CONTAINERS = {
    "顺序执行", "条件执行", "随机执行", "遍历目标", "重复执行",
    "尝试执行", "事务执行",
}

#: `时序.json -> 来源层级`。排序链里它排最前，所以跨方向先后已由它决定，
#: 只有同层内的冲突才需要 `优先级` / `结算顺序`。
SOURCE_LAYERS = {
    "战场环境": 0, "阵法": 10, "功法": 20, "器律": 30,
    "真意": 40, "战丹": 50, "状态": 60, "战斗对象": 70, "战场规则": 80,
}

#: 一场战斗里同时能存在几份。用于剔掉**不可能共存**的组：
#: 战场环境只有一个，所以 27 张地的 `修改判定` 之间永远不会冲突，
#: 不建这个模就会把它们全列成待办（这正是先前虚报的来源）。
#: 注意：上限 ≥2 仍然只是「可以共存」，不等于「实际上会同场同事件触发」，
#: 真实工作面必须靠**实测共现**（跑战斗、记录同一事件上同时触发的监听）来定。
CO_PRESENCE = {
    "战场环境": 1, "阵法": 1, "功法": 6, "真意": 6,
    "气机": 6, "器律": 4, "战丹": 6, "伤势": 6,
}

SURFACES = (
    ("功法", "战斗/内容/功法/功法-*.json"),
    ("真意", "战斗/内容/真意/真意-*.json"),
    ("气机", "战斗/内容/气机/气机-*.json"),
    ("战场环境", "战斗/内容/战场环境/*.json"),
    ("器律", "炼器/内容/器律-*.json"),
    ("战丹", "丹药/内容/战丹/战丹-*.json"),
    ("伤势", "丹药/内容/伤势/*.json"),
)


def corpus(root: pathlib.Path):
    for direction, pattern in SURFACES:
        for path in sorted(root.glob(pattern)):
            if path.name.startswith("说明"):
                continue
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for entry in document if isinstance(document, list) else [document]:
                if isinstance(entry, dict):
                    yield direction, path, entry


def abilities(node, out: list[str]) -> None:
    """把一棵能力树里出现的原子能力名列出来（钻进组合能力）。"""

    if isinstance(node, dict):
        name = node.get("能力")
        if isinstance(name, str):
            out.append(name)
            if name in CONTAINERS or name in ("触发技能", "回放效果"):
                pass
        for value in node.values():
            abilities(value, out)
    elif isinstance(node, list):
        for value in node:
            abilities(value, out)


def listeners(node, out: list[dict]) -> None:
    """收集监听节点；监听体内部不再当监听看。"""

    if isinstance(node, dict):
        if node.get("能力") == "监听事件" and node.get("事件"):
            out.append(node)
            return
        for value in node.values():
            listeners(value, out)
    elif isinstance(node, list):
        for value in node:
            listeners(value, out)


def classify(node: dict) -> tuple[set[str], set[str]]:
    """把这个监听体的「写」与「读」落到**具体的共享量**上。

    必须落到具体量，粒度粗了指标就废：把「造成伤害/恢复资源」也算成写「资源」
    时，人人都写资源，于是 2395 条「行动结束」配出 65 万对冲突，什么也筛不出来。
    """

    writes: set[str] = set()
    reads: set[str] = set()

    def visit(item) -> None:
        if isinstance(item, dict):
            name = item.get("能力")
            if name in EVENT_WRITERS:
                writes.add(EVENT_WRITERS[name])
            if name in STATE_WRITERS:
                writes.add(STATE_WRITERS[name])
            if name == "标签条件":
                reads.add("事件标签")
            if name in ("读取数值", "数值条件"):
                # `数值条件` 的左值通常就是一棵 `读取数值`，一并取到。
                reads.add(READ_SOURCES.get(str(item.get("来源")), ""))
            for value in item.values():
                visit(value)
        elif isinstance(item, list):
            for value in item:
                visit(value)

    visit(node.get("效果") or ())
    if node.get("条件"):
        visit(node["条件"])
    return writes - {""}, reads - {""}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--数据", dest="data", default=str(ROOT / "data"))
    parser.add_argument("--报告", dest="report", default="_监听顺序.txt")
    args = parser.parse_args()

    root = pathlib.Path(args.data).resolve()
    # event -> 声明列表（只用于计数）
    table: dict[str, list[dict]] = collections.defaultdict(list)
    # event -> 卡 -> {写, 读, 未标写的声明数, 已标声明数}
    by_card: dict[str, dict[str, dict]] = collections.defaultdict(dict)
    for pattern, path, entry in corpus(root):
        found: list[dict] = []
        listeners(entry, found)
        card = f"{entry.get('编号')} {entry.get('名称')}"
        direction = pattern
        for node in found:
            writes, reads = classify(node)
            event = str(node["事件"])
            marked = node.get("优先级") is not None
            table[event].append({"卡": card, "写": writes, "优先级": node.get("优先级")})
            body = by_card[event].setdefault(
                card, {"方向": direction, "层级": SOURCE_LAYERS.get(direction, 99),
                       "写": set(), "读": set(),
                       "未标写": 0, "已标": 0, "声明": 0}
            )
            body["写"] |= writes
            body["读"] |= reads
            body["声明"] += 1
            if marked:
                body["已标"] += 1
            elif writes:
                body["未标写"] += 1

    out = io.TextIOWrapper(open(ROOT / args.report, "wb"), encoding="utf-8")
    out.write(f"监听顺序盘点：{root}\n")
    out.write("判据：只有改写**共享量**（事件数值/判定/资源/属性/行动条/冷却/事件存活）的\n")
    out.write("监听才可能因为先后改变结果；只读自己计量的不算。\n\n")

    def conflicts(event: str):
        """**同层内**的读写交集。

        `来源层级` 排在排序链最前，所以跨方向的先后（功法 < 器律 < 真意 < 战丹 …）
        已经由它解决了，不需要 `优先级`。真正需要定序的只有同一层内互相冲突的卡。
        """

        cards = by_card[event]
        layers: dict[int, list[str]] = collections.defaultdict(list)
        for name, body in cards.items():
            # 每场只能存在一份的来源（战场环境、阵法）内部不可能冲突。
            if CO_PRESENCE.get(body["方向"], 99) < 2:
                continue
            layers[body["层级"]].append(name)
        partners: collections.Counter = collections.Counter()
        keys: dict[str, set[str]] = collections.defaultdict(set)
        pairs = 0
        for layer, names in layers.items():
            names.sort()
            for index, left in enumerate(names):
                for right in names[index + 1:]:
                    shared = cards[left]["写"] & (cards[right]["写"] | cards[right]["读"])
                    shared |= cards[right]["写"] & cards[left]["读"]
                    if shared:
                        pairs += 1
                        partners[left] += 1
                        partners[right] += 1
                        keys[left] |= shared
                        keys[right] |= shared
        return pairs, partners, keys

    # 一、总览
    out.write("=" * 100 + "\n")
    out.write("一、哪些事件上存在改写者（顺序可能影响结果）\n")
    out.write("=" * 100 + "\n")
    out.write(f"{'事件':<16}{'声明':>6}{'改写者':>7}{'缺优先级':>9}"
              f"{'涉及词条':>9}{'有交集的卡对':>13}\n")
    overview = []
    for event in table:
        cards = by_card[event]
        writers = sum(1 for item in table[event] if item["写"])
        missing = sum(body["未标写"] for body in cards.values())
        if not writers:
            continue
        pairs, _partners, _keys = conflicts(event)
        overview.append((pairs, event, len(table[event]), writers, missing, len(cards)))
    for pairs, event, total, writers, missing, ncards in sorted(overview, reverse=True):
        out.write(f"{event:<16}{total:>6}{writers:>7}{missing:>9}{ncards:>9}{pairs:>13}\n")
    out.write(f"\n事件种类 {len(table)}；有改写者的事件 {len(overview)}；"
              f"监听声明合计 {sum(len(v) for v in table.values())}\n")
    out.write(f"缺口合计（改写者未标优先级）: {sum(row[4] for row in overview)}\n")

    # 二、待办：同层内与本事件别的词条有交集、且改写声明未标优先级
    out.write("\n" + "=" * 100 + "\n")
    out.write("二、待办清单：同层内有读写交集、且自己的改写声明未标优先级\n")
    out.write("（跨方向的先后已由「来源层级」解决，所以只列同层竞争）\n")
    out.write("=" * 100 + "\n")
    layer_name = {v: k for k, v in SOURCE_LAYERS.items()}
    todo_cards = 0
    for pairs, event, _total, _writers, _missing, _ncards in sorted(overview, reverse=True):
        if not pairs:
            continue
        cards = by_card[event]
        _p, partners, keys = conflicts(event)
        todo = [name for name in sorted(cards)
                if cards[name]["未标写"] and partners.get(name)]
        if not todo:
            continue
        todo_cards += len(todo)
        grouped: dict[int, list[str]] = collections.defaultdict(list)
        for name in todo:
            grouped[cards[name]["层级"]].append(name)
        out.write(f"\n### {event}  同层竞争对 {pairs}，待办 {len(todo)} 张\n")
        for layer in sorted(grouped):
            out.write(f"  ── 来源层级 {layer}（{layer_name.get(layer, '?')}）"
                      f"{len(grouped[layer])} 张\n")
            for name in grouped[layer]:
                body = cards[name]
                out.write(f"      {name:<32} "
                          f"未标改写 {body['未标写']}/{body['声明']}  "
                          f"同层对手 {partners[name]:>3}  "
                          f"交集 {'/'.join(sorted(keys[name]))}\n")
    out.write(f"\n待办词条合计 {todo_cards}（按事件重复计）\n")

    # 三、既有约定
    out.write("\n" + "=" * 100 + "\n")
    out.write("三、既有约定：已声明优先级的取值分布（按事件）\n")
    out.write("=" * 100 + "\n")
    for event in sorted(table):
        marked = [i for i in table[event] if i["优先级"] is not None]
        if not marked:
            continue
        values = collections.Counter(int(i["优先级"]) for i in marked)
        sample = "、".join(f"{i['卡']}={i['优先级']}" for i in marked[:4])
        out.write(f"  {event:<16} {dict(sorted(values.items()))}\n      {sample}\n")

    out.write("\n注：这是**静态 triage**，不是权威待办，有三层已知的虚报，读的时候要打折：\n")
    out.write("  1. 属性改写是经状态修饰间接发生的，这里按「调用添加/移除状态」近似；\n")
    out.write("  2. `状态` 这个键不区分具体状态名，两张卡各碰各的状态也会被算成有交集；\n")
    out.write("  3. 只按共存上限剔除了单份来源（战场环境、阵法）；上限 ≥2 的方向仍然\n")
    out.write("     只是「可以共存」，不等于「实际上会同场、同事件触发」。\n")
    out.write("真实工作面要靠**实测共现**：跑战斗、记录同一事件上同时触发了哪些监听，\n")
    out.write("再对共现过的那些组定序。静态表只用来圈定候选范围。\n")
    out.write("另外：判别先后是作者意图，写写冲突尤其如此——不要按这张表批量刷值。\n")
    out.flush()
    print(f"详见 {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
