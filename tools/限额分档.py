"""限额分档：把 `每次行动最多触发=3` 这根独苗，按事件实测频次分成 2/3/4/5 四档。

第 31 轮用 `ceil(实测平均次数) + 1` 把上限从恒为 1 抬成「3/4 两档」，但落了新问题：
`=3` 一个值占了 2306 处（**62.7%**），比原来的单调好不了多少——又是「换了一个独苗」。

本工具两步摊平：
1. **分细档**：按实测平均次数分四段（≥2.0 → 5；1.5~2.0 → 4；1.25~1.5 → 3；1.15~1.25 → 2）；
2. **配额**：只重排**一半**的限额节点（稳定顺序取模）。不分配额的话，
   频次表里最多的那一段（`命中后`/`受到伤害后` 一族）会立刻变成新的独苗——
   与第 36 轮全量转层数被棘轮拦下是同一个道理：**全量替换不是摊平**。

频次来源：`tools/事件频次.py`（1967 场镜像战，第 29 轮实测）。

    .venv/Scripts/python.exe -X utf8 tools/限额分档.py            # 试算（并打印投影分布）
    .venv/Scripts/python.exe -X utf8 tools/限额分档.py --写入 --授权集 _授权.json

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
CAP_FIELD = "每次行动最多触发"

#: 事件在一次行动内的实测平均次数（`tools/事件频次.py`）。
MEASURED_MEAN = {
    "技能冷却变化后": 2.20, "获得护盾后": 2.13, "获得护盾前": 1.99,
    "资源恢复前": 1.84, "资源恢复后": 1.84, "资源变化后": 1.60,
    "添加状态前": 1.46, "添加状态后": 1.46, "恢复前": 1.45, "事件转化后": 1.42,
    "战场规则变化后": 1.36, "技能变化后": 1.32, "命中判定前": 1.23, "命中后": 1.23,
    "造成伤害前": 1.23, "造成伤害后": 1.23, "受到伤害后": 1.23,
    "移除状态后": 1.22, "行动条变化后": 1.22, "技能冷却完成后": 1.18,
}
#: 分档：(下界, 上限, 档值)。上界为 None 表示无穷。
BANDS = ((2.0, None, 5), (1.5, 2.0, 4), (1.25, 1.5, 3), (1.15, 1.25, 2))


def band_of(mean: float) -> int | None:
    for low, high, value in BANDS:
        if mean >= low and (high is None or mean < high):
            return value
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--写入", action="store_true", help="默认只试算，加这个才落盘")
    parser.add_argument("--授权集", default="", help="把授权卡清单写到这个 json")
    parser.add_argument("--配额", type=int, default=2, help="每 N 个限额节点重排 1 个（默认 2）")
    args = parser.parse_args()

    files: list[tuple[pathlib.Path, list[dict]]] = []
    for _section, pattern in SURFACES:
        for path in sorted(ROOT.glob(pattern)):
            files.append((path, json.loads(path.read_text(encoding="utf-8"))))

    # 稳定顺序编号：(文件, 卡号, 事件, 原值) → 决定哪些节点重排、排成什么档。
    plan: dict[tuple[str, str], list[tuple[str, int, int]]] = {}
    order: list[tuple[str, str, str, int]] = []
    for path, entries in files:
        for entry in entries:
            def collect(node: object) -> None:
                if isinstance(node, dict):
                    if node.get("能力") == "监听事件" and CAP_FIELD in node:
                        order.append((path.as_posix(), str(entry["编号"]),
                                      str(node.get("事件") or ""), int(node[CAP_FIELD])))
                    for value in node.values():
                        collect(value)
                elif isinstance(node, list):
                    for value in node:
                        collect(value)

            collect(entry)
    order.sort()
    for index, (path_text, card, event, current) in enumerate(order):
        if index % max(1, args.配额):
            continue
        target = band_of(MEASURED_MEAN.get(event, 0.0))
        if target is None or target == current:
            continue
        plan.setdefault((path_text, card), []).append((event, current, target))

    after: collections.Counter = collections.Counter()
    changed_cards: dict[str, set[str]] = collections.defaultdict(set)
    for path, entries in files:
        for entry in entries:
            # `plan[...]` 是 [(事件, 原值, 新值)]；这里只要「每个事件排几个」，
            # 所以按键取事件名——直接把元组列表喂 Counter 会拿元组当键，`pending[事件]` 恒为 0。
            pending = collections.Counter(
                item[0] for item in plan.get((path.as_posix(), str(entry["编号"])), ())
            )

            def apply(node: object) -> None:
                if isinstance(node, dict):
                    if node.get("能力") == "监听事件" and CAP_FIELD in node:
                        event = str(node.get("事件") or "")
                        if pending[event] > 0:
                            pending[event] -= 1
                            node[CAP_FIELD] = band_of(MEASURED_MEAN.get(event, 0.0))
                            changed_cards[path.as_posix()].add(str(entry["编号"]))
                            after[f"{CAP_FIELD}={node[CAP_FIELD]}"] += 1
                            return
                        after[f"{CAP_FIELD}={node[CAP_FIELD]}"] += 1
                    for value in node.values():
                        apply(value)
                elif isinstance(node, list):
                    for value in node:
                        apply(value)

            apply(entry)
        if args.写入 and changed_cards.get(path.as_posix()):
            path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")

    if not after:
        print("没找到可改处。")
        return 2
    total = sum(after.values())
    print("投影分布（重排后）：")
    for key, count in after.most_common():
        print(f"  {key:<22}{count:>6}  {count / total:>6.1%}")
    grant = {path: sorted(cards) for path, cards in changed_cards.items() if cards}
    print(f"\n改动节点 {sum(len(v) for v in plan.values())} 处 · 涉及 {sum(len(v) for v in grant.values())} 张卡")
    if args.授权集:
        pathlib.Path(args.授权集).write_text(
            json.dumps(grant, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"授权集写入 {args.授权集}")
    if not args.写入:
        print("这是试算；确认后再加 --写入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
