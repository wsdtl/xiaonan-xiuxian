"""计数器转层数：把卡内私有 `构筑计量` 换成卡面可见的 `状态层数`。

口径第 1 条要摊平的两个最大项是同一个惯用法（效果动词 `修改构筑计量` 56.0%、
缩放来源 `构筑计量` 63.2%）。本工具把它改成「状态层数」——引擎本来就有层数机制，
而且层数**写在卡面上读者看得见**，比一个隐形计数器有特色。

**逐计数器判定**（一张卡有几个计数器就配几个印记）：
- 计数器**增量是值节点**（如 `读取本次数值×10%`）→ 该计数器跳过（`层数` 字段在引擎里是
  `float(...)`，喂 dict 会崩）；
- 计数器有 `方式=设置` → 该计数器跳过（层数没有"设为 N"的语义）；
- 其余计数器都转；一张卡一个都没得转就整张不动。

改法（每个计数器 C）：
- 在**第一个监听节点的效果表开头**插一条 `添加状态`：状态名照 C，`层数上限 = 原最高值 + 1`，
  `重复方式: 增加层数`，`持续单位: 整场战斗`。
  （插入点必须在监听节点内：`能力[].效果[0]` 必须是监听节点，`检查构筑形状` 会拦。）
- `修改构筑计量{方式:增加, 数值:N}` → `增加状态层数{状态:选择状态(C), 层数:N}`
- `修改构筑计量{方式:清空}` → `消耗状态层数{状态:选择状态(C), 方式:减少, 层数:上限+1, 不足时是否失败:false}`
- `读取数值{来源:构筑计量, 计量:C}` → `读取数值{来源:状态层数, 状态:C, 目标:自身}`

**层数常驻 +1**（清空只能清到 1 层，0 层会被引擎连状态一起移除），所以判定要补偿：
把 `数值条件` 里的**字面量**按比较符与左右侧各挪 1，使判定在 `stacks = 计数 + 1` 下等价。
这样读数不必包 `计算数值`，卡面文字保持可读。

    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/计数器转层数.py            # 试算
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/计数器转层数.py --写入 --授权集 _授权.json

**退出码：0 = 正常，2 = 没找到可改处。**
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SURFACES = (
    ("功法", "data/战斗/内容/功法/功法-*.json"),
    ("真意", "data/战斗/内容/真意/真意-*.json"),
    ("气机", "data/战斗/内容/气机/气机-*.json"),
    ("器律", "data/物品/炼器/内容/器律-*.json"),
)
SELF_TARGET = {"能力": "选择目标", "范围": "自身"}
#: 读在**左值**时，字面量（右值）的挪动表：stacks = 计数 + 1。
LEFT_LITERAL_SHIFT = {"大于等于": -1, "大于": +1, "小于等于": +1, "小于": -1, "等于": +1, "不等于": +1}


def selector(counter: str) -> dict:
    """`增加/消耗状态层数` 的 `状态` 字段要求是 `选择状态` 能力节点（见 `原子能力.json`）。"""
    return {"能力": "选择状态", "目标": dict(SELF_TARGET), "名称": counter}


def census(entry: dict) -> dict[str, object]:
    """逐个计数器收集：方式集合、最高值、增量是否为值节点。"""
    counters: dict[str, dict[str, object]] = {}
    statuses: set[str] = set()

    def note(name: str) -> dict[str, object]:
        return counters.setdefault(name, {"方式": set(), "最高值": 0, "值节点": False})

    def walk(node: object) -> None:
        if isinstance(node, dict):
            ability = str(node.get("能力") or "")
            if ability == "修改构筑计量":
                info = note(str(node.get("计量") or ""))
                info["方式"].add(str(node.get("方式") or "增加"))  # type: ignore[union-attr]
                info["最高值"] = max(int(info["最高值"]), int(node.get("最高值") or 0))  # type: ignore[arg-type]
                if not isinstance(node.get("数值"), (int, float)) or isinstance(node.get("数值"), bool):
                    info["值节点"] = True  # type: ignore[assignment]
            elif ability == "读取数值" and node.get("来源") == "构筑计量":
                note(str(node.get("计量") or ""))
            elif ability == "添加状态":
                status = node.get("状态")
                if isinstance(status, dict):
                    statuses.add(str(status.get("名称") or ""))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(entry)
    counters.pop("", None)
    statuses.discard("")
    return {"counters": counters, "statuses": statuses}


def convert(entry: dict, targets: dict[str, int]) -> collections.Counter:
    stats: collections.Counter = collections.Counter()

    def is_read_of(node: object, counter: str) -> bool:
        return (isinstance(node, dict) and node.get("能力") == "读取数值"
                and node.get("来源") == "构筑计量"
                and str(node.get("计量") or "") == counter)

    def adjust_condition(node: dict, counter: str) -> None:
        compare = str(node.get("比较") or "")
        for side, other in (("左值", "右值"), ("右值", "左值")):
            if not is_read_of(node.get(side), counter):
                continue
            literal = node.get(other)
            if not isinstance(literal, (int, float)) or isinstance(literal, bool):
                continue
            if side == "右值":
                # 字面量在左：`字面量 OP 计数` ⟺ `字面量+1 OP stacks`，与比较符无关。
                node[other] = literal + 1
            else:
                shift = LEFT_LITERAL_SHIFT.get(compare)
                if shift is None:
                    continue
                node[other] = literal + shift
            stats["挪字面量"] += 1

    def rewrite(node: object) -> None:
        if isinstance(node, dict):
            ability = str(node.get("能力") or "")
            if ability == "数值条件":
                for counter in targets:
                    adjust_condition(node, counter)
            name = str(node.get("计量") or "")
            if ability == "修改构筑计量" and name in targets:
                mode = str(node.get("方式") or "增加")
                cap = targets[name]
                node.pop("计量", None)
                node.pop("最高值", None)
                # `增加状态层数` 只允许 `状态`/`层数`；`消耗状态层数` 额外允许 `方式`/
                # `不足时是否失败`。原节点的 `目标` 由 `选择状态` 自带，必须删掉。
                node.pop("目标", None)
                node["状态"] = selector(name)
                if mode == "增加":
                    node.pop("方式", None)
                    node["能力"] = "增加状态层数"
                    node["层数"] = max(1, int(node.pop("数值", 1) or 1))
                else:
                    amount = int(node.pop("数值", 0) or 0)
                    node["能力"] = "消耗状态层数"
                    node["方式"] = "减少"
                    node["层数"] = max(1, amount) if mode == "减少" else max(2, cap + 1)
                    node["不足时是否失败"] = False
                stats["写"] += 1
            else:
                for counter in targets:
                    if is_read_of(node, counter):
                        node["来源"] = "状态层数"
                        node["状态"] = counter
                        node["目标"] = dict(SELF_TARGET)
                        node.pop("计量", None)
                        stats["读"] += 1
                        break
            for value in node.values():
                rewrite(value)
        elif isinstance(node, list):
            for value in node:
                rewrite(value)

    rewrite(entry)

    markers = []
    for counter, cap in targets.items():
        markers.append({"能力": "添加状态", "目标": dict(SELF_TARGET),
                        "状态": {"名称": counter, "类别": "正面", "持续单位": "整场战斗",
                                 "剩余行动": 1, "层数上限": max(2, cap + 1),
                                 "重复方式": "增加层数", "属性": {}}})

    def plant(node: object) -> bool:
        if isinstance(node, dict):
            if node.get("能力") == "监听事件" and isinstance(node.get("效果"), list):
                node["效果"][0:0] = [dict(marker) for marker in markers]
                stats["插"] += len(markers)
                return True
            for value in node.values():
                if plant(value):
                    return True
        elif isinstance(node, list):
            for value in node:
                if plant(value):
                    return True
        return False

    if not plant(entry):
        stats["插"] = 0
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--写入", action="store_true", help="默认只试算，加这个才落盘")
    parser.add_argument("--授权集", default="", help="把授权卡清单写到这个 json")
    parser.add_argument("--配额", type=int, default=2,
                        help="每 N 个计数器转 1 个（默认 2 = 转一半）。全转只是把集中度从"
                             " 构筑计量 搬到 状态层数（棘轮会拦），配额才能压缩最大项。")
    args = parser.parse_args()

    total: collections.Counter = collections.Counter()
    grant: dict[str, list[str]] = {}
    skipped: collections.Counter = collections.Counter()
    files: list[tuple[pathlib.Path, list[dict]]] = []
    for _section, pattern in SURFACES:
        for path in sorted(ROOT.glob(pattern)):
            files.append((path, json.loads(path.read_text(encoding="utf-8"))))

    # 先按稳定顺序（文件 → 卡号 → 计数器名）给所有可转计数器编号，再按配额取一部分。
    # 全转只是把集中度从 `构筑计量` 搬到 `状态层数`（棘轮当场拦下：59.7% → 63.3%）；
    # 配额才能让两种机制各占一块，压缩**最大项**才是摊平。稳定顺序保证可复现。
    order: list[tuple[str, str, str]] = []
    for path, entries in files:
        for entry in entries:
            for counter, row in census(entry)["counters"].items():  # type: ignore[union-attr]
                if row["值节点"]:
                    skipped["增量是值节点"] += 1
                    continue
                if "设置" in row["方式"]:  # type: ignore[operator]
                    skipped["含设置"] += 1
                    continue
                order.append((path.as_posix(), str(entry["编号"]), counter))
    order.sort()
    plan: dict[tuple[str, str], set[str]] = {}
    for index, (path_text, card, counter) in enumerate(order):
        if index % max(1, args.配额) == 0:
            plan.setdefault((path_text, card), set()).add(counter)
    skipped["按配额留在原样"] += len(order) - sum(len(v) for v in plan.values())

    for path, entries in files:
        cards: list[str] = []
        for entry in entries:
            targets = plan.get((path.as_posix(), str(entry["编号"])))
            if not targets:
                continue
            caps = {name: int(row["最高值"])
                    for name, row in census(entry)["counters"].items()  # type: ignore[union-attr]
                    if name in targets}
            stats = convert(entry, caps)
            if not stats["插"]:
                skipped["没找到监听节点"] += 1
                continue
            total.update(stats)
            cards.append(str(entry["编号"]))
        if cards:
            grant[path.relative_to(ROOT).as_posix()] = sorted(cards)
            if args.写入:
                path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")

    if not total:
        print("没找到可改处。")
        print("跳过：" + " · ".join(f"{k} {v}" for k, v in skipped.most_common()))
        return 2
    print(f"\n合计：插状态 {total['插']} · 改写 {total['写']} · 改读 {total['读']}"
          f" · 挪字面量 {total['挪字面量']} · 涉及 {sum(len(v) for v in grant.values())} 张卡")
    print("跳过/留存：" + " · ".join(f"{k} {v}" for k, v in skipped.most_common()))
    if args.授权集:
        pathlib.Path(args.授权集).write_text(
            json.dumps(grant, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"授权集写入 {args.授权集}")
    if not args.写入:
        print("这是试算；确认后再加 --写入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
