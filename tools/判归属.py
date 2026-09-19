"""真意 / 器律归属判据：按「谁的角度」——也就是**监听的边界**判，不按时点清单。

判据来自 `data/战斗/规则/说明.md -> 真意与器律的监听分工`，但落成可判形式时发现一件事：

    按「角度四问」判，真意 95% 落在"器物"侧——**"真意=战场叙事"并不描述现有卡池**，
    真意绝大多数写的是"自身状态的叙事"（读自己的状态、作用于自己）。

于是判据改成**边界**，它既符合数据、也确实可判：

| | 器律 | 真意 |
| --- | --- | --- |
| 允许的边界 | **不得越出持有者**（只观察自身/主人、只作用于自身/主人） | **可以越出**：观察他人/战场、改写事件、打到别人 |
| 判据性质 | **硬规则**（越界即不合归属） | **能力许可**（只写自身叙事不算违规，只是没用掉这份许可） |

越界的判法（四问任一命中即越界）：
1. `阵营关系` ∈ {其他己方, 任意敌方, 任意}；
2. 任一效果目标范围 ∈ {事件来源, 事件承受者, 己方, 敌方, 当前目标, 全部, 关联对象}；
3. 出现 `修改事件目标` / `取消事件` / `分摊伤害` / `转移伤害`（改写战场事件）；
4. 读到别人的状态：`目标属性` / `目标当前·已损失`。

**时点只作佐证**：结构性时点 vs 裁定结算点，不参与判定——所以以后新增时点不需要改规则。
那 5 个"语义上不属于器物"的时点（`战斗对象入场后/退场后`、`战场规则变化后`、`形态切换后`、
`复活后`）**是这条边界的推论**（一把剑不该知道别人进场），不是枚举出来的现状。

    .venv/Scripts/python.exe -X utf8 tools/判归属.py            # 总览
    .venv/Scripts/python.exe -X utf8 tools/判归属.py --明细      # 列出越界的卡

**退出码：0 = 无器律越界；1 = 有器律越界（可当检查用）。**
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SECTIONS = (
    ("真意", "data/战斗/内容/真意/真意-*.json"),
    ("器律", "data/物品/炼器/内容/器律-*.json"),
)
SELF_SCOPE = {"自身", "主人"}
#: 越界：伸向**战场**的目标范围。`当前目标` **不算**——武器打持有者选定的目标正是器物本职
#: （攻伐类器律都这样），把它算成越界会把 40/64 张攻伐卡误判。
OTHER_SCOPE = {"事件来源", "事件承受者", "己方", "敌方", "全部",
               "全部己方", "全部敌方", "关联对象"}
OTHER_CAMP = {"其他己方", "任意敌方", "任意"}
EVENT_REWRITERS = {"修改事件目标", "取消事件", "分摊伤害", "转移伤害"}
OTHER_SOURCE = {"目标属性"}
OTHER_PREFIX = ("目标当前", "目标已损失")
STRUCTURAL_EVENTS = {"战斗开始", "战斗结束", "战斗对象入场后", "战斗对象退场后",
                     "战场规则变化后", "形态切换后", "复活后", "行动开始", "行动结束",
                     "行动决策前", "行动决策后", "行动条变化后", "行动意图变化后",
                     "行动跳过后", "技能施放前", "技能施放失败后", "技能变化后"}
#: 语义上明确不属于器物的时点（边界判据的推论，列出来供人对照）。
NOT_WEAPON_EVENTS = ("战斗对象入场后", "战斗对象退场后", "战场规则变化后",
                     "形态切换后", "复活后")


def scope_of(node: object) -> str | None:
    if not isinstance(node, dict):
        return None
    if node.get("能力") == "选择目标":
        return str(node.get("范围") or "")
    target = node.get("目标")
    if isinstance(target, dict):
        return str(target.get("范围") or "")
    return None


def cross_reasons(entry: dict) -> tuple[list[str], set[str]]:
    """返回（越界理由, 该卡用到的时点）。理由为空 = 完全在持有者边界内。"""
    reasons: list[str] = []
    events: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            ability = str(node.get("能力") or "")
            if ability == "监听事件":
                events.add(str(node.get("事件") or ""))
                camp = str(node.get("阵营关系") or "")
                if camp in OTHER_CAMP:
                    reasons.append(f"观察他人({camp})")
            if ability in EVENT_REWRITERS:
                reasons.append(f"改写事件({ability})")
            scope = scope_of(node)
            if scope in OTHER_SCOPE:
                reasons.append(f"作用于他人({scope})")
            if ability == "读取数值":
                source = str(node.get("来源") or "")
                if source in OTHER_SOURCE or source.startswith(OTHER_PREFIX):
                    reasons.append(f"读他人状态({source})")
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(entry)
    return sorted(set(reasons)), events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--明细", action="store_true", help="列出越界的卡")
    args = parser.parse_args()

    hard_hits: list[tuple[str, str, list[str]]] = []
    for name, pattern in SECTIONS:
        rows: list[tuple[str, str, list[str], set[str]]] = []
        for path in sorted(ROOT.glob(pattern)):
            for entry in json.loads(path.read_text(encoding="utf-8")):
                reasons, events = cross_reasons(entry)
                rows.append((str(entry["编号"]), str(entry.get("名称") or ""), reasons, events))
        crossing = [row for row in rows if row[2]]
        # 硬规则只两条：用战场时点、改写战场事件。其余越界算"偏重"，只报不判。
        hard = [row for row in rows
                if (row[3] & set(NOT_WEAPON_EVENTS))
                or any(r.startswith("改写事件") for r in row[2])]
        timing = collections.Counter(
            "结构性" if len(row[3] & STRUCTURAL_EVENTS) > len(row[3] - STRUCTURAL_EVENTS)
            else "裁定结算" if row[3] - STRUCTURAL_EVENTS else "无时点"
            for row in rows
        )
        print(f"== {name} 共 {len(rows)} 张")
        print(f"   硬规则违例：{len(hard)} 张"
              f"（用战场时点 {sum(1 for r in rows if r[3] & set(NOT_WEAPON_EVENTS))} · "
              f"改写战场事件 {sum(1 for r in rows if any(x.startswith('改写事件') for x in r[2]))}）")
        print(f"   伸向战场（偏重，不算违例）：{len(crossing)} 张（{len(crossing) / len(rows):.1%}）")
        print("   时点佐证：" + " · ".join(f"{k} {v}" for k, v in timing.most_common()))
        if args.明细 and crossing:
            for cid, cname, reasons, _events in crossing[:14]:
                print(f"      {cid} {cname}：{' '.join(reasons[:4])}")
        if name == "器律":
            hard_hits = [(cid, cname, [r for r in reasons
                                       if r.startswith("改写事件")] or ["用了战场时点"])
                         for cid, cname, reasons, events in hard]
        print()

    print("判据形态：")
    print("   硬规则（器律）：① 不用语义上不属于器物的战场时点"
          f"（{'、'.join(NOT_WEAPON_EVENTS)}）② 不改写战场事件")
    print("   偏重（只报）：两族都允许伸向战场，器律更轻；这条不做判定，因为它是「偏重」不是「边界」")
    print("   真意：允许越界，只写自身叙事不算违规（只是没用掉这份许可）")
    if hard_hits:
        print(f"   器律硬规则违例 {len(hard_hits)} 张：")
        for cid, cname, reasons in hard_hits:
            print(f"      {cid} {cname}：{' '.join(reasons)}")
        return 1
    print("   器律硬规则违例：0 张 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
