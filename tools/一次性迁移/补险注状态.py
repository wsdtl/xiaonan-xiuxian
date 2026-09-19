"""给读取「险注」层数的 36 张卡补上那个缺失的层数状态（方案 A：当状态补）。

病灶：36 张卡一律写 `读取数值 来源=状态层数 状态=险注 目标=自身`，却**没有任何一张卡
施加它**，所以读到的永远是 0。原文说明把语义写清楚了，例如 400264：

    ④[太岳真躯宝身篇·计量·太岳蓄元]
    •自身行动结束时，若太岳蓄元达到3，按自身[险注]层数对当前目标造成等量真实伤害（每层1点）；

补法（统一规则，不逐卡手写）：

1. 每张卡造一个自我施加的层数状态，名字按现行规范取「卡名前缀 + 功法负面场景词」，
   全局唯一，偶数前缀阶梯；
2. 累积点：在**该卡驱动这条裁定的计量**每一次 `修改构筑计量 … 方式=增加` 的后面，
   紧跟一个 `添加状态`，把新状态加到自身一层；
3. 把 36 处读取从 `险注` 改指到新名字。

参数是设计判断，集中放在下面，改一处就能整体调。

**这不是等价改写**：那 36 处读取原本恒为 0，补完之后裁定才开始真的造成伤害。
所以改完必须跑 `tools/语料对照.py`，差异就是这次补的内容本身。

    python tools/一次性迁移/补险注状态.py            # 预演
    python tools/一次性迁移/补险注状态.py --apply
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

#: 要补的那个状态名。
TARGET = "险注"
#: 状态定义：整场战斗累积，不按行动递减。
DURATION_UNIT = "整场战斗"
REMAINING = 1
CATEGORY = "负面"
REPEAT = "增加层数"
#: 层数上限。取该卡驱动裁定的那个计量的 `最高值`（缺省 5），与「清零后重新积累」一致。
DEFAULT_CAP = 5
#: 只用偶数前缀阶梯，切点在两字词边界上。
LADDER = (2, 4, 6, 8, 10)


def status_word(entity: rename.Entity) -> tuple[str, ...]:
    table = rename.STATUS_WORDS.get(entity.kind) or rename.DEFAULT_STATUS_WORDS
    return tuple(table.get(CATEGORY) or rename.DEFAULT_STATUS_WORDS[CATEGORY])


def reads_target(node) -> bool:
    return (
        isinstance(node, dict)
        and node.get("能力") == "读取数值"
        and node.get("来源") == "状态层数"
        and node.get("状态") == TARGET
    )


def gate_counters(entity: rename.Entity) -> set[str]:
    """找出驱动「读 TARGET 的那条裁定」的计量名。"""

    counters: set[str] = set()

    def scan(node, inside: bool):
        if isinstance(node, dict):
            if node.get("能力") == "条件执行":
                found = any(reads_target(child) for child in rename.walk(node))
                for child in rename.walk(node):
                    if child.get("能力") == "读取数值" and child.get("来源") == "构筑计量":
                        name = child.get("计量")
                        if isinstance(name, str) and found:
                            counters.add(name)
                scan(node.get("成立效果"), inside)
                scan(node.get("不成立效果"), inside)
                return
            for value in node.values():
                scan(value, inside)
        elif isinstance(node, list):
            for value in node:
                scan(value, inside)

    scan(entity.payload, False)
    return counters


def cap_for(entity: rename.Entity, counters: set[str]) -> int:
    for node in rename.walk(entity.payload):
        if node.get("能力") == "修改构筑计量" and node.get("计量") in counters:
            value = node.get("最高值")
            if value is not None:
                return int(value)
    return DEFAULT_CAP


def apply_card(entity: rename.Entity, taken: set[str], stats) -> tuple[str | None, int]:
    """补一张卡；返回 (新状态名, 累积点个数)。"""

    counters = gate_counters(entity)
    if not counters:
        stats["找不到驱动计量，跳过"] += 1
        return None, 0

    name = None
    for length in LADDER:
        if length >= len(entity.name):
            break
        for word in status_word(entity):
            candidate = entity.name[:length] + word
            if candidate not in taken:
                name = candidate
                break
        if name:
            break
    if name is None:
        for word in status_word(entity):
            candidate = entity.name + word
            if candidate not in taken:
                name = candidate
                break
    if name is None:
        stats["取名失败，跳过"] += 1
        return None, 0
    taken.add(name)

    cap = cap_for(entity, counters)
    definition = {
        "名称": name,
        "类别": CATEGORY,
        "持续单位": DURATION_UNIT,
        "剩余行动": REMAINING,
        "重复方式": REPEAT,
        "层数上限": cap,
    }
    applied = {"能力": "添加状态",
               "目标": {"能力": "选择目标", "范围": "自身"},
               "状态": definition}

    added = {"n": 0}

    def rebuild(node):
        if isinstance(node, list):
            kept = []
            for item in node:
                rebuilt = rebuild(item)
                kept.append(rebuilt)
                if isinstance(item, dict) and item.get("能力") == "修改构筑计量":
                    if item.get("计量") in counters and item.get("方式") == "增加":
                        kept.append(dict(applied))
                        added["n"] += 1
            return kept
        if isinstance(node, dict):
            if reads_target(node):
                stats["改指读取"] += 1
                return {**node, "状态": name}
            return {key: rebuild(value) for key, value in node.items()}
        return node

    rebuilt = rebuild(entity.payload)
    entity.payload.clear()
    entity.payload.update(rebuilt)
    return name, added["n"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写回数据文件")
    parser.add_argument("--报告", dest="report", default="_输出/补险注状态.txt")
    args = parser.parse_args()

    entities = rename.load_entities()
    alive = set()
    for entity in entities:
        alive |= set(entity.counters) | set(entity.statuses)
    taken = set(alive)

    stats: collections.Counter = collections.Counter()
    rows: list[str] = []
    targets = 0
    for entity in entities:
        if not any(reads_target(node) for node in rename.walk(entity.payload)):
            continue
        targets += 1
        name, points = apply_card(entity, taken, stats)
        rows.append(f"{entity.identity}\t{entity.name}\t{name or '—'}\t累积点 {points}")

    changed = rename.write_back(entities) if args.apply else []

    (ROOT / "_输出").mkdir(exist_ok=True)
    out = io.TextIOWrapper(open(ROOT / args.report, "wb"), encoding="utf-8")
    out.write(f"读「{TARGET}」层数的卡 {targets} 张\n")
    for key, count in stats.most_common():
        out.write(f"  {count:>6}  {key}\n")
    out.write(f"\n改动文件 {len(changed)}\n")
    out.write("模式: " + ("已写回" if args.apply else "预演") + "\n\n")
    out.write("卡号\t卡名\t新状态名\t累积点\n")
    for line in rows:
        out.write(line + "\n")
    out.flush()

    print(f"目标 {targets} 张；"
          + "，".join(f"{k} {v}" for k, v in stats.most_common())
          + f"；改动文件 {len(changed)}；详见 {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
