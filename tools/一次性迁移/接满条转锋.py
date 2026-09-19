"""把「满条转锋」读的那条老词汇表的「势」接到本卡自己的蓄积计量上。

五张卡形状完全一致，原文说明也是同一句模板：

    满条转锋：若自身〈X势〉大于等于5，进入[某极]（攻击+10、防御+10）

`〈X势〉` 是老词汇表的词（时势 / 潮势 / 谋势 / 锁势），全库没人积累它，条件永远不成立。
这几张卡自己都有计量，但该读哪一个数据里读不出来：上限全是 100/999，没有「条=5」的信号；
原文说明写的也是老名字，不是判据。

**设计判断（本脚本的依据）**：`蓄` 就是「蓄积」，正是「满条」该读的量。
五张卡里四张恰好都有一个 `*蓄元`；`400030` 只有一个计量，直接用它。
于是规则统一为：**接该卡名字里带「蓄」的计量，没有就用它唯一的计量。**

这不是编新机制，是把已有零件接上：只改读取点的引用，不新增节点。
改完「满条转锋」才会真的触发，所以会改平衡——判据是「差异必须全部落在这 5 张卡里，外部 0 处」。

    python tools/一次性迁移/接满条转锋.py            # 预演
    python tools/一次性迁移/接满条转锋.py --apply
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

#: 要接的卡 -> 它读的那条老「势」。
TARGETS = {
    "400016": "潮势",
    "400283": "时势",
    "400431": "时势",
    "400030": "谋势",
    "400524": "锁势",
}

#: 选蓄积计量的优先字：`蓄` 即蓄积，正是「满条」该读的量。
PREFERRED = "蓄"


def own_counters(entity: rename.Entity) -> list[str]:
    names = []
    for node in rename.walk(entity.payload):
        if node.get("能力") == "修改构筑计量":
            name = node.get("计量")
            if isinstance(name, str) and name not in names:
                names.append(name)
    return names


def choose(entity: rename.Entity, counters: list[str], stats) -> str | None:
    preferred = [name for name in counters if PREFERRED in name]
    if len(preferred) == 1:
        stats["按「蓄」字选中"] += 1
        return preferred[0]
    if len(counters) == 1:
        stats["唯一计量"] += 1
        return counters[0]
    stats["选不出来，跳过"] += 1
    return None


def patch(entity: rename.Entity, old: str, stats) -> str | None:
    counters = own_counters(entity)
    if old in counters:
        stats["本来就对，跳过"] += 1
        return old
    chosen = choose(entity, counters, stats)
    if chosen is None:
        return None

    def rebuild(node):
        if isinstance(node, list):
            return [rebuild(item) for item in node]
        if isinstance(node, dict):
            if (
                node.get("能力") == "读取数值"
                and node.get("来源") == "构筑计量"
                and node.get("计量") == old
            ):
                stats["改指读取"] += 1
                return {**node, "计量": chosen}
            return {key: rebuild(value) for key, value in node.items()}
        return node

    rebuilt = rebuild(entity.payload)
    entity.payload.clear()
    entity.payload.update(rebuilt)
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写回数据文件")
    parser.add_argument("--报告", dest="report", default="_输出/接满条转锋.txt")
    args = parser.parse_args()

    entities = rename.load_entities()
    stats: collections.Counter = collections.Counter()
    rows: list[str] = []
    for entity in entities:
        old = TARGETS.get(entity.identity)
        if old is None:
            continue
        chosen = patch(entity, old, stats)
        rows.append(f"{entity.identity}\t{entity.name}\t{old}\t{chosen or '—'}")

    changed = rename.write_back(entities) if args.apply else []

    (ROOT / "_输出").mkdir(exist_ok=True)
    out = io.TextIOWrapper(open(ROOT / args.report, "wb"), encoding="utf-8")
    out.write(f"目标 {len(TARGETS)} 张卡\n")
    for key, count in stats.most_common():
        out.write(f"  {count:>4}  {key}\n")
    out.write(f"\n改动文件 {len(changed)}\n")
    out.write("模式: " + ("已写回" if args.apply else "预演") + "\n\n")
    out.write("卡号\t卡名\t老势\t接到的计量\n")
    for line in rows:
        out.write(line + "\n")
    out.flush()

    print(f"目标 {len(TARGETS)} 张；"
          + "，".join(f"{k} {v}" for k, v in stats.most_common())
          + f"；改动文件 {len(changed)}；详见 {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
