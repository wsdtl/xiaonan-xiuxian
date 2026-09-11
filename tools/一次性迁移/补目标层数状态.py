"""收掉第二批剩下的 8 个尾巴：给「只读目标身上层数、却没人上过这个状态」的卡补上施加点。

这 8 张卡形状完全一致：

    主动技能.效果[N] = 条件执行(… , 成立效果=[造成伤害(数值=读取 当前目标的<状态>层数)])

也就是「按目标身上的层数打伤害」，但全库没有一处给目标上过这个状态，层数恒为 0，
伤害句永远算 0。上一批（`补缺失状态.py`）能锚到「对状态的第一个操作」，这 8 张只有读取、
没有操作可锚，所以留了下来。

补法（统一，不逐卡手写）：在**含这条读取的那门主动技能的效果列表最前面**，插一个
`添加状态`（目标=当前目标），让这门技能每用一次就给目标记一层，随后的伤害句读得到。

参数集中在下面。这是补内容、会改平衡，判据是「差异必须全部落在这 8 张卡里，外部 0 处」。

    python tools/一次性迁移/补目标层数状态.py            # 预演
    python tools/一次性迁移/补目标层数状态.py --apply
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import io
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rename = _load("词条改名", "tools/一次性迁移/重命名词条.py")
audit = _load("词条作用域", "tools/架构审查/检查词条作用域.py")

#: 要收的 8 个尾巴：卡号 -> 上一批已经改指好的本卡专属状态名。
TAILS = {
    "400070": "龙象灵标",
    "400044": "周天灵标",
    "400210": "朱雀灵标",
    "400342": "三才灵标",
    "400365": "紫微灵纪",
    "400485": "枯荣灵数",
    "400530": "龙吟灵标",
    "400569": "血炼灵纪",
}

CATEGORY = "中性"
DURATION_UNIT = "状态承受者行动"
REMAINING = 3
REPEAT = "增加层数"
STACK_CAP = 5


def reads(node, name: str) -> bool:
    return (
        isinstance(node, dict)
        and node.get("能力") == "读取数值"
        and node.get("来源") == "状态层数"
        and node.get("状态") == name
    )


def contains_read(node, name: str) -> bool:
    return any(reads(child, name) for child in rename.walk(node))


def patch(entity: rename.Entity, name: str, stats) -> bool:
    """在含读取的那门主动技能的效果列表最前面插一个施加点。"""

    abilities = entity.payload.get("能力")
    if not isinstance(abilities, list):
        stats["没有能力数组"] += 1
        return False
    for skill in abilities:
        if not isinstance(skill, dict) or skill.get("能力") != "主动技能":
            continue
        effects = skill.get("效果")
        if not isinstance(effects, list) or not contains_read(skill, name):
            continue
        skill["效果"] = [
            {
                "能力": "添加状态",
                "目标": {"能力": "选择目标", "范围": "当前目标"},
                "状态": {
                    "名称": name,
                    "类别": CATEGORY,
                    "持续单位": DURATION_UNIT,
                    "剩余行动": REMAINING,
                    "重复方式": REPEAT,
                    "层数上限": STACK_CAP,
                },
            },
            *effects,
        ]
        stats["插入施加点"] += 1
        return True
    stats["找不到含读取的主动技能"] += 1
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写回数据文件")
    parser.add_argument("--报告", dest="report", default="_补目标层数状态.txt")
    args = parser.parse_args()

    entities = rename.load_entities()
    stats: collections.Counter = collections.Counter()
    rows: list[str] = []
    for entity in entities:
        name = TAILS.get(entity.identity)
        if name is None:
            continue
        ok = patch(entity, name, stats)
        rows.append(f"{entity.identity}\t{entity.name}\t{name}\t{'已插施加点' if ok else '未处理'}")

    changed = rename.write_back(entities) if args.apply else []

    out = io.TextIOWrapper(open(ROOT / args.report, "wb"), encoding="utf-8")
    out.write(f"目标 {len(TAILS)} 张卡\n")
    for key, count in stats.most_common():
        out.write(f"  {count:>4}  {key}\n")
    out.write(f"\n改动文件 {len(changed)}\n")
    out.write("模式: " + ("已写回" if args.apply else "预演") + "\n\n")
    out.write("卡号\t卡名\t状态名\t结果\n")
    for line in rows:
        out.write(line + "\n")
    out.flush()

    print(f"目标 {len(TAILS)} 张；"
          + "，".join(f"{k} {v}" for k, v in stats.most_common())
          + f"；改动文件 {len(changed)}；详见 {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
