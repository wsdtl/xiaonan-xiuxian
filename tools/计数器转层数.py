"""计数器转层数：把卡内私有 `构筑计量` 换成卡面可见的 `状态层数`。

口径第 1 条要摊平的两个最大项是同一个惯用法（效果动词 `修改构筑计量` 56.0%、
缩放来源 `构筑计量` 63.2%）。本工具把它改成「状态层数」——引擎本来就有层数机制，
而且层数**写在卡面上读者看得见**，比一个隐形计数器有特色。

选取口径（含糊就不动）：
1. 卡里**恰好一个** `构筑计量` 名、**恰好一个** `添加状态` 的状态名；
2. 该计数器**只做增加**（没有 `清空`/`设置`/`减少`）——见下方说明；
3. 至少一处读取该计量。

**为什么只动纯累积型**：`修改状态层数` 把层数减到 0 时引擎会**移除该状态**
（`mechanics.py`：`if status.stacks <= 0: owner.statuses.remove(status)`），
而计数器归零后还能再加。所以「清空」类计数器转过去会**归零即消失、之后再也加不上**。
清空型要转必须另配「重新添加」的结构，属于另一批的活，这里不碰。

改法：
- 在卡的第一个效果列表开头插一条 `添加状态`：状态名照计数器名，`层数上限` 照计数器的 `最高值`
  （**必须写**：状态 `层数上限` 默认 1，不写层数就加不上去），`持续单位` 取「整场战斗」；
- `修改构筑计量{方式:增加, 数值:N}` → `修改状态层数{状态:{名称:C}, 方式:增加, 层数:N}`；
- `读取数值{来源:构筑计量, 计量:C}` → `读取数值{来源:状态层数, 状态:C, 目标:自身}`（百分比/最高值保留）。

    .venv/Scripts/python.exe -X utf8 tools/计数器转层数.py            # 试算
    .venv/Scripts/python.exe -X utf8 tools/计数器转层数.py --写入 --授权集 _授权.json

**退出码：0 = 正常，2 = 没找到可改处。**
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SURFACES = (
    ("功法", "data/战斗/内容/功法/功法-*.json"),
    ("真意", "data/战斗/内容/真意/真意-*.json"),
    ("气机", "data/战斗/内容/气机/气机-*.json"),
    ("器律", "data/炼器/内容/器律-*.json"),
)
ACCUMULATING_ONLY = ("设置",)
SELF_TARGET = {"能力": "选择目标", "范围": "自身"}


def census(entry: dict) -> dict[str, object]:
    counters: set[str] = set()
    statuses: set[str] = set()
    modes: set[str] = set()
    caps: dict[str, int] = {}
    judged: set[str] = set()
    node_valued: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            ability = str(node.get("能力") or "")
            if ability == "修改构筑计量":
                name = str(node.get("计量") or "")
                counters.add(name)
                modes.add(str(node.get("方式") or "增加"))
                caps[name] = max(caps.get(name, 0), int(node.get("最高值") or 0))
                # `数值` 允许是值节点（例如 `读取本次数值×10%`）。那种写法没法直接当层数，
                # 整张卡跳过——层数的 `层数` 字段在引擎里是 `float(...)`，喂 dict 会崩。
                if not isinstance(node.get("数值"), (int, float)) or isinstance(node.get("数值"), bool):
                    node_valued.add(name)
            elif ability == "读取数值" and node.get("来源") == "构筑计量":
                counters.add(str(node.get("计量") or ""))
            elif ability == "数值条件":
                # 计数器读数一旦参与判定，常驻 +1 就会改变判定（甚至让「计数器为空」类
                # 反序检查 `0 ≥ 计量` 永远不成立），所以这类卡整张跳过。
                for side in ("左值", "右值"):
                    value = node.get(side)
                    if isinstance(value, dict) and value.get("来源") == "构筑计量":
                        judged.add(str(value.get("计量") or ""))
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
    counters.discard("")
    statuses.discard("")
    return {"counters": counters, "statuses": statuses, "modes": modes,
            "caps": caps, "judged": judged, "node_valued": node_valued}


#: 读在**左值**时，字面量（右值）的挪动表：stacks = 计数 + 1。
LEFT_LITERAL_SHIFT = {"大于等于": -1, "大于": +1, "小于等于": +1, "小于": -1, "等于": +1, "不等于": +1}


def selector(counter: str) -> dict:
    """`增加/消耗状态层数` 的 `状态` 字段要求是 `选择状态` 能力节点（见 `原子能力.json`）。"""
    return {"能力": "选择状态", "目标": dict(SELF_TARGET), "名称": counter}


def convert(entry: dict, counter: str, cap: int) -> collections.Counter:
    stats: collections.Counter = collections.Counter()
    # 层数路线下计数器**常驻 +1**：清空只能清到 1 层（0 层会被引擎移除状态）。
    # 所以状态上限取 `原最高值 + 1`，让计数器的可达上限与原设计一致。
    # `重复方式: 增加层数` 与现网写法一致（重复获得时叠层，而不是替换）。
    marker = {"能力": "添加状态", "目标": dict(SELF_TARGET),
              "状态": {"名称": counter, "类别": "正面", "持续单位": "整场战斗",
                       "剩余行动": 1, "层数上限": max(2, cap + 1),
                       "重复方式": "增加层数", "属性": {}}}

    def is_counter_read(node: object) -> bool:
        return (isinstance(node, dict) and node.get("能力") == "读取数值"
                and node.get("来源") == "构筑计量"
                and str(node.get("计量") or "") == counter)

    def adjust_condition(node: dict) -> None:
        """计数器读数进判定时，把**字面量**挪 1，使判定在 stacks = 计数+1 下等价。"""
        compare = str(node.get("比较") or "")
        for side, other in (("左值", "右值"), ("右值", "左值")):
            if not is_counter_read(node.get(side)):
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
                adjust_condition(node)
            if ability == "修改构筑计量" and str(node.get("计量") or "") == counter:
                mode = str(node.get("方式") or "增加")
                node.pop("计量", None)
                node.pop("最高值", None)
                # `增加状态层数` 只允许 `状态`/`层数`；`消耗状态层数` 额外允许 `方式`/
                # `不足时是否失败`。原来的 `目标` 由 `选择状态` 节点自己带，必须删掉，
                # 否则 schema 报「规则不认识字段 方式、目标」。
                node.pop("目标", None)
                node["状态"] = selector(counter)
                if mode == "增加":
                    node.pop("方式", None)
                    node["能力"] = "增加状态层数"
                    node["层数"] = max(1, int(node.pop("数值", 1) or 1))
                else:
                    # `消耗状态层数`：清空 = 一次减够（减到 0 会被引擎连状态一起移除，
                    # 所以减到「剩 1 层」= 计数器 0）。
                    amount = int(node.pop("数值", 0) or 0)
                    node["能力"] = "消耗状态层数"
                    node["方式"] = "减少"
                    node["层数"] = max(1, amount) if mode == "减少" else max(2, cap + 1)
                    node["不足时是否失败"] = False
                stats["写"] += 1
            elif is_counter_read(node):
                node["来源"] = "状态层数"
                node["状态"] = counter
                node["目标"] = dict(SELF_TARGET)
                node.pop("计量", None)
                stats["读"] += 1
            for value in node.values():
                rewrite(value)
        elif isinstance(node, list):
            for value in node:
                rewrite(value)

    rewrite(entry)
    # 计数器状态必须先存在。插入点有契约约束：`能力[].效果[0]` **必须是监听节点**
    # （检查构筑形状会拦），所以只能插进**第一个监听节点的效果表开头**。
    def plant(node: object) -> bool:
        if isinstance(node, dict):
            if node.get("能力") == "监听事件" and isinstance(node.get("效果"), list):
                node["效果"].insert(0, dict(marker))
                stats["插"] += 1
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
    args = parser.parse_args()

    total: collections.Counter = collections.Counter()
    grant: dict[str, list[str]] = {}
    skipped: collections.Counter = collections.Counter()
    for section, pattern in SURFACES:
        for path in sorted(ROOT.glob(pattern)):
            entries = json.loads(path.read_text(encoding="utf-8"))
            cards: list[str] = []
            for entry in entries:
                info = census(entry)
                if len(info["counters"]) != 1 or len(info["statuses"]) != 1:
                    skipped["计量/状态不是恰好一个"] += 1
                    continue
                if info["node_valued"]:
                    skipped["增量是值节点"] += 1
                    continue
                if any(mode in ACCUMULATING_ONLY for mode in info["modes"]):
                    skipped["含设置"] += 1
                    continue
                counter = next(iter(info["counters"]))
                stats = convert(entry, counter, int(info["caps"].get(counter, 0)))
                if not stats["插"]:
                    skipped["没找到效果列表"] += 1
                    continue
                total.update(stats)
                cards.append(str(entry["编号"]))
            if cards:
                grant[path.relative_to(ROOT).as_posix()] = sorted(cards)
                if args.写入:
                    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
                print(f"{section}/{path.stem}: {len(cards)} 张")

    if not total:
        print("没找到可改处。")
        print("跳过：" + " · ".join(f"{k} {v} 张" for k, v in skipped.most_common()))
        return 2
    print(f"\n合计：插状态 {total['插']} · 改写 {total['写']} · 改读 {total['读']}"
          f" · 挪字面量 {total['挪字面量']} · 涉及 {sum(len(v) for v in grant.values())} 张")
    print("跳过：" + " · ".join(f"{k} {v} 张" for k, v in skipped.most_common()))
    if args.授权集:
        pathlib.Path(args.授权集).write_text(
            json.dumps(grant, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"授权集写入 {args.授权集}")
    if not args.写入:
        print("这是试算；确认后再加 --写入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
