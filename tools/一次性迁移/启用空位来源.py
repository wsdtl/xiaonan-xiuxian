"""启用空位来源：把 0 次使用的 `行动条` / `技能冷却` 用上（按卡名主题分配）。

第 30 轮的读数显示引擎支持、全库 0 次使用的读取来源有四个：`固定值` / `效果来源属性` /
`行动条` / `技能冷却`。本工具启用后两个，按**卡名主题**决定给谁（不是随机撒）：

    卡名含 时/序/先/追/步/影/疾/速  → 读 `行动条`（行动越靠前，效果越强）
    卡名含 蓄/势/伏/藏            → 读 `技能冷却`（憋得越久，爆发越强）

**必须同时补 `目标` 为自身。** 引擎里 `行动条` / `技能冷却`（和 `构筑计量` / `状态层数`）
读的是**读数节点 `目标` 所指的人**，而 `自身属性` 是隐含读自己——只换 `来源` 会把
「自己的行动条」读成「目标的行动条」。所以换源时补上
`"目标": {"能力": "选择目标", "范围": "自身"}`，与现网的 `构筑计量` 读法一致。

百分比按新来源的**量纲**给（强度不设限，但要量级合理，别造出天文数字）：

    行动条 ∈ [0, 100]  → 百分比 100（满行动条 = 100 点）
    技能冷却 = 冷却之和（约 0~10）→ 百分比 500（满冷却 ≈ 50 点）

    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/启用空位来源.py            # 试算
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/启用空位来源.py --写入 --授权集 _授权.json

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
#: 主题词 → (新来源, 百分比)。
THEMES = (
    (("蓄", "势", "伏", "藏"), ("技能冷却", 500)),
    (("时", "序", "先", "追", "步", "影", "疾", "速"), ("行动条", 100)),
)
SELF_TARGET = {"能力": "选择目标", "范围": "自身"}


def theme_of(name: str) -> tuple[str, int] | None:
    for keys, outcome in THEMES:
        if any(key in name for key in keys):
            return outcome
    return None


def rewrite(path: pathlib.Path, *, write: bool) -> tuple[collections.Counter, list[str]]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    changes: collections.Counter = collections.Counter()
    cards: list[str] = []

    for entry in entries:
        outcome = theme_of(str(entry.get("名称") or ""))
        if outcome is None:
            continue
        origin, percent = outcome

        def walk(node: object) -> None:
            if isinstance(node, dict):
                if node.get("能力") == "读取数值" and node.get("来源") == "自身属性":
                    node["来源"] = origin
                    node.pop("属性", None)
                    node["百分比"] = percent
                    node["目标"] = dict(SELF_TARGET)
                    changes[origin] += 1
                    cid = str(entry["编号"])
                    if cid not in cards:
                        cards.append(cid)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(entry)

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
            print(f"{section}/{path.stem}: {sum(changes.values())} 处（{len(cards)} 张）"
                  f" {' '.join(f'{k}×{v}' for k, v in sorted(changes.items()))}")

    if not total:
        print("没找到可改处。")
        return 2
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
