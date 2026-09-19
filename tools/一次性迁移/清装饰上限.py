"""清装饰上限：删掉写在「一次行动至多发生一次」的事件上的 `每次行动最多触发`。

第 29 轮的实测（`tools/事件频次.py`，1967 场）把范围钉死了：`行动开始` / `行动决策前` /
`行动决策后` / `行动结束` / `普通攻击前` / `普通攻击后` / `战斗开始` / `战斗结束` 这 8 种事件
**每次行动（或每场战斗）恰好发生一次**（行动内最大次数 = 1，0.0% 的行动超过一次）。
写在这些事件上的「每次行动最多触发 = 1」**永远碰不到**，是装饰性的：

- 它让 `限额形态` 的集中度读数虚高（83.8% 挤在同一个值上，其中一大块是噪音）；
- 它让卡面「明细」行满屏重复一句没有约束力的话，真正在限流的上限反而看不出来。

所以删掉，**零强度代价**（第 6 轮已实测同位置改动 1264 场差异 0）。

只动这 8 种**结构性单次**事件。数据上「恰好只出现一次」的稀有事件（`闪避后` /
`行动跳过后` / `技能施放失败后` / `添加状态失败后` / `行动意图变化后`）不碰——
它们的单次是**样本结论**，不是结构保证，删掉可能在没测到的构筑里放开触发。

    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/清装饰上限.py              # 试算
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/清装饰上限.py --写入 --授权集 _授权.json

**退出码：0 = 正常，2 = 没找到可删处。**
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
#: 结构上每次行动（或每场战斗）只发一次的事件——第 29 轮实测：行动内最大次数 = 1。
STRUCTURAL_SINGLE = (
    "行动开始", "行动决策前", "行动决策后", "行动结束",
    "普通攻击前", "普通攻击后", "战斗开始", "战斗结束",
)


def clean(path: pathlib.Path, *, write: bool) -> tuple[collections.Counter, list[str]]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    removed: collections.Counter = collections.Counter()
    cards: list[str] = []

    def walk(node: object, event: str, card: str) -> None:
        if isinstance(node, dict):
            here = str(node.get("事件") or event)
            if (
                node.get("能力") == "监听事件"
                and here in STRUCTURAL_SINGLE
                and "每次行动最多触发" in node
            ):
                removed[f"{here}={node.pop('每次行动最多触发')}"] += 1
                if card not in cards:
                    cards.append(card)
            for value in node.values():
                walk(value, here, card)
        elif isinstance(node, list):
            for value in node:
                walk(value, event, card)

    for entry in entries:
        walk(entry, "", str(entry["编号"]))
    if write and sum(removed.values()):
        path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return removed, sorted(cards)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--写入", action="store_true", help="默认只试算，加这个才落盘")
    parser.add_argument("--授权集", default="", help="把授权卡清单写到这个 json")
    args = parser.parse_args()

    total: collections.Counter = collections.Counter()
    grant: dict[str, list[str]] = {}
    for section, pattern in SURFACES:
        for path in sorted(ROOT.glob(pattern)):
            removed, cards = clean(path, write=args.写入)
            if not removed:
                continue
            total.update(removed)
            grant[path.relative_to(ROOT).as_posix()] = cards
            keys = " ".join(f"{k}×{v}" for k, v in sorted(removed.items()))
            print(f"{section}/{path.stem}: {sum(removed.values())} 处（{len(cards)} 张） {keys}")

    if not total:
        print("没找到可删的装饰上限。")
        return 2
    print(f"\n合计 {sum(total.values())} 处 · 涉及 {sum(len(v) for v in grant.values())} 张"
          f"（按文件计，同一张卡只出现在一个文件里）")
    if args.授权集:
        pathlib.Path(args.授权集).write_text(
            json.dumps(grant, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"授权集写入 {args.授权集}")
    if not args.写入:
        print("这是试算；确认后再加 --写入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
