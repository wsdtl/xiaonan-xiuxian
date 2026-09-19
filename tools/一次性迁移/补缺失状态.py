"""给「被增删改查、却从来没被创建」的状态补上定义（通用版，`补险注状态.py` 的推广）。

病灶：卡里对一个状态做 `增加状态层数 / 延长状态 / 复制状态 / 消耗状态层数 / 支付代价`，
但全库没有任何一张卡创建它。读到的层数恒为 0，操作等于空转。

统一三步（不逐卡手写）：

1. 每张卡为它引用的那个名字造一个**本卡专属**状态，名字按现行规范取
   （卡名前缀 + 场景词，全局唯一，偶数前缀阶梯）；
2. 把该卡所有引用改指到新名字；
3. 在该卡对该状态的**第一个操作之前**插一个 `添加状态`，目标**跟着那个操作的目标走**
   ——自身操作用自身，`当前目标` 操作用当前目标。

参数是设计判断，集中在下面。`类别` 一律取 `中性`：这是注册表默认值，也最保守——
不会被动用「正面/负面」的泛选状态意外扫到。

**这是补内容、会改平衡**：原来恒为 0 的读数补完就有效果了。语料对照会出现差异，
判据是「差异必须全部落在本次授权的卡里，外部 0 处」。

    python tools/一次性迁移/补缺失状态.py            # 预演
    python tools/一次性迁移/补缺失状态.py --apply
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

#: 状态定义参数。
CATEGORY = "中性"
DURATION_UNIT = "状态承受者行动"
REMAINING = 3
REPEAT = "增加层数"
STACK_CAP = 5

LADDER = (2, 4, 6, 8, 10)

#: 会「用到」一个状态的能力：在这些能力之前必须先把它创建出来。
OPERATIONS = {
    "增加状态层数", "延长状态", "缩短状态", "消耗状态层数",
    "移除状态", "复制状态", "转移状态", "支付代价",
}


def status_word(entity: rename.Entity) -> tuple[str, ...]:
    table = rename.STATUS_WORDS.get(entity.kind) or rename.DEFAULT_STATUS_WORDS
    return tuple(table.get(CATEGORY) or rename.DEFAULT_STATUS_WORDS[CATEGORY])


def referenced(node, dead: set[str]) -> str | None:
    """这个节点若是作用在某个悬空状态上的操作，返回那个名字。"""

    if not isinstance(node, dict):
        return None
    ability = node.get("能力")
    # 顶层实体的 `能力` 是一个数组，不是能力名——不能直接拿去 `in` 集合。
    if not isinstance(ability, str) or ability not in OPERATIONS:
        return None
    holder = node.get("状态")
    name = holder.get("名称") if isinstance(holder, dict) else None
    return name if name in dead else None


def read_only(node, dead: set[str]) -> str | None:
    if (
        isinstance(node, dict)
        and node.get("能力") == "读取数值"
        and node.get("来源") == "状态层数"
        and node.get("状态") in dead
    ):
        return node["状态"]
    return None


def pick_name(entity: rename.Entity, taken: set[str]) -> str | None:
    for length in LADDER:
        if length >= len(entity.name):
            break
        for word in status_word(entity):
            candidate = entity.name[:length] + word
            if candidate not in taken:
                return candidate
    for word in status_word(entity):
        candidate = entity.name + word
        if candidate not in taken:
            return candidate
    return None


def patch_card(entity: rename.Entity, dead: set[str], taken: set[str], stats, rows):
    """补一张卡；就地改 payload。"""

    names = set()
    for node in rename.walk(entity.payload):
        found = referenced(node, dead) or read_only(node, dead)
        if found:
            names.add(found)
    if not names:
        return

    mapping: dict[str, str] = {}
    for old in sorted(names):
        new = pick_name(entity, taken)
        if new is None:
            stats["取名失败"] += 1
            continue
        taken.add(new)
        mapping[old] = new

    if not mapping:
        return

    created: set[str] = set()

    def rebuild(node):
        if isinstance(node, list):
            kept = []
            for item in node:
                act = referenced(item, dead)
                if act and act in mapping:
                    new = mapping[act]
                    if new not in created:
                        created.add(new)
                        target = item.get("目标") or {"能力": "选择目标", "范围": "自身"}
                        kept.append({
                            "能力": "添加状态",
                            "目标": target,
                            "状态": {
                                "名称": new,
                                "类别": CATEGORY,
                                "持续单位": DURATION_UNIT,
                                "剩余行动": REMAINING,
                                "重复方式": REPEAT,
                                "层数上限": STACK_CAP,
                            },
                        })
                        stats["插入累积点"] += 1
                kept.append(rebuild(item))
            return kept
        if isinstance(node, dict):
            if read_only(node, dead) and node["状态"] in mapping:
                stats["改指读取"] += 1
                return {**node, "状态": mapping[node["状态"]]}
            act = referenced(node, dead)
            if act and act in mapping:
                stats["改指操作"] += 1
                holder = dict(node["状态"]) if isinstance(node.get("状态"), dict) else node.get("状态")
                if isinstance(holder, dict):
                    holder["名称"] = mapping[act]
                return {**node, "状态": holder}
            return {key: rebuild(value) for key, value in node.items()}
        return node

    rebuilt = rebuild(entity.payload)
    entity.payload.clear()
    entity.payload.update(rebuilt)
    for old, new in sorted(mapping.items()):
        rows.append(f"{entity.identity}\t{entity.name}\t{entity.kind}\t{old}\t{new}\t"
                    f"{'已插累积点' if new in created else '只改指（无操作点）'}")
    if len(created) < len(mapping):
        stats["只改指未插点"] += len(mapping) - len(created)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写回数据文件")
    parser.add_argument("--报告", dest="report", default="_输出/补缺失状态.txt")
    args = parser.parse_args()

    found = audit.collect()
    dead = {n for n, r in found["状态"].items() if not r["定义"] and r["读取"]}

    entities = rename.load_entities()
    taken: set[str] = set()
    for entity in entities:
        taken |= set(entity.counters) | set(entity.statuses)

    stats: collections.Counter = collections.Counter()
    rows: list[str] = []
    for entity in entities:
        patch_card(entity, dead, taken, stats, rows)

    changed = rename.write_back(entities) if args.apply else []

    (ROOT / "_输出").mkdir(exist_ok=True)
    out = io.TextIOWrapper(open(ROOT / args.report, "wb"), encoding="utf-8")
    out.write(f"悬空状态名 {len(dead)} 个\n")
    for key, count in stats.most_common():
        out.write(f"  {count:>6}  {key}\n")
    out.write(f"\n改动文件 {len(changed)}\n")
    out.write("模式: " + ("已写回" if args.apply else "预演") + "\n\n")
    out.write("卡号\t卡名\t方向\t旧名\t新名\t累积点\n")
    for line in rows:
        out.write(line + "\n")
    out.flush()

    print(f"处理 {len(rows)} 处；"
          + "，".join(f"{k} {v}" for k, v in stats.most_common())
          + f"；改动文件 {len(changed)}；详见 {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
