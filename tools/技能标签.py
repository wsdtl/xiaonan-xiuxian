"""技能标签词表：给 `主动技能` 按**技能自己的结构**打标签。

现状：515 个 `主动技能` 节点里只有 120 个带标签，且全是 `群体` 一个词——词表等于没在用。
标签**不是装饰**：`选择技能` 会按标签筛选技能（`mechanics.py` 的 `_select_skills` 读
`selector["标签"]`），卡面「明细」也会打印它（`card_text.py`）。

按结构判定（每条都对应技能真实在做的事，可复查）：

| 标签 | 判定依据 |
| --- | --- |
| `群体` | 技能效果里有打向**多个**敌人的选择目标（范围=敌方且带排序/全体） |
| `单体` | 有伤害/减益，但目标不是多个 |
| `疗愈` | 含 `恢复资源` |
| `守势` | 含 `获得护盾` 或加「防御/格挡/护盾/减伤」类属性的状态 |
| `连击` | 含 2 个以上 `造成伤害`，或含 `追加攻击` |
| `代价` | 含对**自身**的 `资源消耗` |
| `强化` | 含给自身/己方的正面 `添加状态` |
| `控制` | 含 `是否控制` 为真的状态 |

    .venv/Scripts/python.exe -X utf8 tools/技能标签.py            # 试算（打印词表与分布）
    .venv/Scripts/python.exe -X utf8 tools/技能标签.py --写入 --授权集 _授权.json

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
GUARD_KEYS = {"防御", "格挡率", "格挡减伤", "护盾上限", "护盾加成", "受盾加成", "伤害减免", "韧性"}


def tags_for(skill: dict) -> set[str]:
    # 从**原有标签**出发取并集：不能把卡上已经写好的 `群体` 抹掉（120 → 79 会丢信息）。
    tags: set[str] = {str(item) for item in skill.get("标签") or ()}
    damage = 0
    guarded = False

    def walk(node: object) -> None:
        nonlocal damage, guarded
        if isinstance(node, dict):
            ability = str(node.get("能力") or "")
            if ability == "造成伤害":
                damage += 1
            elif ability in {"恢复资源", "恢复"}:
                tags.add("疗愈")
            elif ability == "获得护盾":
                guarded = True
            elif ability == "追加攻击":
                tags.add("连击")
            elif ability == "资源消耗":
                target = node.get("目标")
                if isinstance(target, dict) and str(target.get("范围") or "") == "自身":
                    tags.add("代价")
            elif ability == "添加状态":
                status = node.get("状态")
                if isinstance(status, dict):
                    if status.get("是否控制"):
                        tags.add("控制")
                    stats = set(dict(status.get("属性") or {})) & GUARD_KEYS
                    if stats:
                        guarded = True
                    if str(status.get("类别") or "") == "正面":
                        tags.add("强化")
            elif ability == "选择目标":
                scope = str(node.get("范围") or "")
                if scope.startswith("敌方") and node.get("排序"):
                    tags.add("群体")
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(skill)
    if damage:
        tags.add("群体" if "群体" in tags else "单体")
        if damage >= 2:
            tags.add("连击")
    if guarded:
        tags.add("守势")
    return tags


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--写入", action="store_true", help="默认只试算，加这个才落盘")
    parser.add_argument("--授权集", default="", help="把授权卡清单写到这个 json")
    args = parser.parse_args()

    before: collections.Counter = collections.Counter()
    after: collections.Counter = collections.Counter()
    combo: collections.Counter = collections.Counter()
    filters = 0
    skills = 0
    changed = 0
    grant: dict[str, list[str]] = {}

    for _section, pattern in SURFACES:
        for path in sorted(ROOT.glob(pattern)):
            entries = json.loads(path.read_text(encoding="utf-8"))
            cards: list[str] = []
            for entry in entries:
                touched = False

                def visit(node: object) -> None:
                    nonlocal filters, skills, changed, touched
                    if isinstance(node, dict):
                        ability = str(node.get("能力") or "")
                        if ability == "选择技能" and node.get("标签"):
                            filters += 1
                        if ability == "主动技能":
                            skills += 1
                            for item in node.get("标签") or ():
                                before[str(item)] += 1
                            tags = sorted(tags_for(node))
                            if tags:
                                node["标签"] = tags
                                for item in tags:
                                    after[item] += 1
                                combo["+".join(tags)] += 1
                                changed += 1
                                touched = True
                        for value in node.values():
                            visit(value)
                    elif isinstance(node, list):
                        for value in node:
                            visit(value)

                visit(entry)
                if touched:
                    cards.append(str(entry["编号"]))
            if cards:
                grant[path.relative_to(ROOT).as_posix()] = sorted(cards)
                if args.写入:
                    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")

    print(f"主动技能节点 {skills} 个 · 打上标签 {changed} 个 "
          f"· 现有「按标签筛技能」的节点 {filters} 个")
    print(f"\n词表：前 {len(before)} 种 → 后 {len(after)} 种")
    print("  前：" + " ".join(f"{k}×{v}" for k, v in before.most_common()))
    print("  后：" + " ".join(f"{k}×{v}" for k, v in after.most_common()))
    print("\n标签组合（前 12）：")
    for key, count in combo.most_common(12):
        print(f"  {count:>4}  {key}")
    if args.授权集:
        pathlib.Path(args.授权集).write_text(
            json.dumps(grant, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"\n授权集写入 {args.授权集}（{sum(len(v) for v in grant.values())} 张卡）")
    if not args.写入:
        print("这是试算；确认后再加 --写入。")
    return 0 if changed else 2


if __name__ == "__main__":
    raise SystemExit(main())
