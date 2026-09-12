"""限额按频次：把可多次触发事件上的 `每次行动最多触发=1` 按**实测频次**定档。

第 29 轮实测（`tools/事件频次.py`，1967 场）给出了每种事件在一次行动内的平均发生次数。
现在的规则是：

    新上限 = ceil(该事件实测平均次数) + 1

也就是「**允许比平均多发生一次**」——上限从「永远碰不到」变成「真的在限流」。
只动**实测平均 ≥ 1.2** 的事件；平均 ≈ 1.0 的事件（结构单次那 8 种，以及 `暴击后` 1.00、
`恢复后` 1.15、`追加攻击*` 1.16）不动：那些位置的上限本来就是装饰性的，第 30 轮已清过结构单次，
剩下的「样本上只出现一次」不动更稳。

结果是把 83.1% 的单一档（全是 1）摊成 3 与 4 两档，且每一档都有实测依据。
负责人口径：机制要平均、强度不设限——所以上限抬升带来的增强**不补偿**，只量只报。

    .venv/Scripts/python.exe -X utf8 tools/限额按频次.py              # 试算
    .venv/Scripts/python.exe -X utf8 tools/限额按频次.py --写入 --授权集 _授权.json

**退出码：0 = 正常，2 = 没找到可改处。**
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SURFACES = (
    ("功法", "data/战斗/内容/功法/功法-*.json"),
    ("真意", "data/战斗/内容/真意/真意-*.json"),
    ("气机", "data/战斗/内容/气机/气机-*.json"),
    ("器律", "data/炼器/内容/器律-*.json"),
)

#: 事件在一次行动内的实测平均次数（来源：`tools/事件频次.py`，1967 场镜像战）。
#: 只列平均 ≥ 1.2 的；新上限 = ceil(平均) + 1。
MEASURED_MEAN = {
    "技能冷却变化后": 2.20,
    "获得护盾后": 2.13,
    "获得护盾前": 1.99,
    "资源恢复前": 1.84,
    "资源恢复后": 1.84,
    "资源变化后": 1.60,
    "添加状态前": 1.46,
    "添加状态后": 1.46,
    "恢复前": 1.45,
    "战场规则变化后": 1.36,
    "技能变化后": 1.32,
    "命中判定前": 1.23,
    "命中后": 1.23,
    "造成伤害前": 1.23,
    "造成伤害后": 1.23,
    "受到伤害后": 1.23,
    "移除状态后": 1.22,
    "行动条变化后": 1.22,
    "技能冷却完成后": 1.18,
    "事件转化后": 1.42,
    "形态切换后": 1.12,
    "关联变化后": 1.05,
    "追加攻击前": 1.16,
    "追加攻击后": 1.16,
    "恢复后": 1.15,
}
THRESHOLD = 1.2


def cap_for(event: str) -> int | None:
    mean = MEASURED_MEAN.get(event)
    if mean is None or mean < THRESHOLD:
        return None
    return math.ceil(mean) + 1


def rewrite(path: pathlib.Path, *, write: bool) -> tuple[collections.Counter, list[str]]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    changes: collections.Counter = collections.Counter()
    cards: list[str] = []

    def walk(node: object, event: str, card: str) -> None:
        if isinstance(node, dict):
            here = str(node.get("事件") or event)
            if node.get("能力") == "监听事件":
                cap = cap_for(here)
                if cap is not None and int(node.get("每次行动最多触发", 1) or 1) == 1:
                    node["每次行动最多触发"] = cap
                    changes[f"{here}:1→{cap}"] += 1
                    if card not in cards:
                        cards.append(card)
            for value in node.values():
                walk(value, here, card)
        elif isinstance(node, list):
            for value in node:
                walk(value, event, card)

    for entry in entries:
        walk(entry, "", str(entry["编号"]))
    if write and sum(changes.values()):
        path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changes, sorted(cards)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--写入", action="store_true", help="默认只试算，加这个才落盘")
    parser.add_argument("--授权集", default="", help="把授权卡清单写到这个 json")
    args = parser.parse_args()

    total: collections.Counter = collections.Counter()
    grant: dict[str, list[str]] = {}
    for section, pattern in SURFACES:
        for path in sorted(ROOT.glob(pattern)):
            changes, cards = rewrite(path, write=args.写入)
            if not changes:
                continue
            total.update(changes)
            grant[path.relative_to(ROOT).as_posix()] = cards

    if not total:
        print("没找到可改处。")
        return 2
    for key, count in sorted(total.items()):
        print(f"  {key:<16} {count:>5} 处")
    print(f"\n合计 {sum(total.values())} 处 · 涉及 {sum(len(v) for v in grant.values())} 张")
    if args.授权集:
        pathlib.Path(args.授权集).write_text(
            json.dumps(grant, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"授权集写入 {args.授权集}")
    if not args.写入:
        print("这是试算；确认后再加 --写入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
