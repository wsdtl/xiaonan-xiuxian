"""把词条名字里「切在词中间」的卡名前缀改回偶数长度。

`重命名词条.py` 生成名字时用 2→3→4→5 字的前缀阶梯，撞名就往长退。三星阶梯
会切在词中间，读起来像两个词粘在一起：

    三花聚鼎炉火录  ->  三花聚归元      （应为 三花聚鼎归元）
    血丹换命炉火录  ->  血丹换归元
    无相化劫符书    ->  无相化劫符归元   （7 字，全库最长）

本脚本只做一件事：对这些名字重新走一遍**偶数阶梯**（2→4→6→…→全名），能短就短，
只改名字、不改结构。定义点与读取点按实体一起改，`说明` 里的长名与裸名沿用
`重命名词条.py` 的替换规则，所以不会出现「JSON 改了、说明没改」。

用法::

    python tools/一次性迁移/修整词条前缀.py            # 预演
    python tools/一次性迁移/修整词条前缀.py --apply    # 写回
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import io
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIBLING = ROOT / "tools" / "一次性迁移" / "重命名词条.py"

_spec = importlib.util.spec_from_file_location("词条改名", SIBLING)
rename = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rename)

#: 只用偶数前缀，保证切点在两字词的边界上。
EVEN_LADDER = (2, 4, 6, 8, 10)


def known_words(entity: rename.Entity, kind: str) -> set[str]:
    """这张卡这个方向用过的全部场景词。"""

    table = rename.COUNTER_WORDS if kind == "计量" else rename.STATUS_WORDS
    default = rename.DEFAULT_COUNTER_WORDS if kind == "计量" else rename.DEFAULT_STATUS_WORDS
    by_kind = table.get(entity.kind) or default
    words: set[str] = set()
    for group in list(by_kind.values()) + list(default.values()):
        words |= set(group)
    return words


def split(entity: rename.Entity, kind: str, name: str) -> tuple[int, str]:
    """把名字拆成 (卡名前缀长度, 场景词)。

    只看「前缀多长」会拆错：`梦丹养元` 既是 `梦丹`+`养元`，也「看起来像」`梦丹养`+`元`。
    所以从最短前缀开始试，**余下部分必须是一个真的场景词**才算数。
    """

    card = entity.name
    words = known_words(entity, kind)
    for length in range(2, len(card) + 1):
        if len(name) <= length or not name.startswith(card[:length]):
            continue
        if name[length:] in words:
            return length, name[length:]
    return 0, ""


def plan_for(entity: rename.Entity, kind: str, pool: dict, taken: set[str]):
    """给出这个实体的改名对；返回 (pairs, 保留原因)。"""

    pairs: list[tuple[str, str, str]] = []
    kept: list[str] = []
    card = entity.name
    for old in sorted(pool):
        length, word = split(entity, kind, old)
        if length == 0 or length % 2 == 0:
            continue
        new = None
        for candidate_length in EVEN_LADDER:
            if candidate_length >= len(card):
                break
            if candidate_length == length:
                continue
            candidate = card[:candidate_length] + word
            if candidate not in taken:
                new = candidate
                break
        if new is None:
            candidate = card + word
            if candidate not in taken and candidate != old:
                new = candidate
        if new is None:
            kept.append(f"{entity.identity} {kind}「{old}」（{length} 字前缀，无可用偶数前缀）")
            continue
        taken.add(new)
        pairs.append((kind, old, new))
    return pairs, kept


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写回数据文件")
    parser.add_argument("--报告", dest="report", default="_输出/前缀修整.txt")
    args = parser.parse_args()

    entities = rename.load_entities()
    all_names: set[str] = set()
    for entity in entities:
        all_names |= set(entity.counters) | set(entity.statuses)

    # 先把要改的名字整体释放，再统一分配，避免互相占位。
    planned: list[tuple[rename.Entity, str, str, str]] = []
    rows_by_identity: dict[str, list[tuple[str, str, str]]] = collections.defaultdict(list)
    for entity in entities:
        for kind, pool in (("计量", entity.counters), ("状态", entity.statuses)):
            for old in pool:
                length, _word = split(entity, kind, old)
                if length and length % 2 == 1:
                    all_names.discard(old)
    taken = set(all_names)
    kept: list[str] = []
    for entity in entities:
        for kind, pool in (("计量", entity.counters), ("状态", entity.statuses)):
            pairs, missed = plan_for(entity, kind, pool, taken)
            kept.extend(missed)
            if pairs:
                rows_by_identity[entity.identity].extend(pairs)
                planned.extend((entity, row[0], row[1], row[2]) for row in pairs)

    leftovers: list[str] = []
    for entity in entities:
        rows = rows_by_identity.get(entity.identity)
        if not rows:
            continue
        for remainder in entity.rename_all(rows):
            leftovers.append(f"{entity.identity} {entity.name}: {remainder}")

    changed = rename.write_back(entities) if args.apply else []

    (ROOT / "_输出").mkdir(exist_ok=True)
    out = io.TextIOWrapper(open(ROOT / args.report, "wb"), encoding="utf-8")
    per_kind = collections.Counter(kind for _, kind, _, _ in planned)
    out.write(f"改名 {len(planned)} 处（计量 {per_kind['计量']}，状态 {per_kind['状态']}）\n")
    out.write(f"无法修整、保持原样 {len(kept)} 处\n")
    for line in kept[:40]:
        out.write(f"  {line}\n")
    out.write(f"\n说明里的残留 {len(leftovers)} 处\n")
    for line in leftovers[:40]:
        out.write(f"  {line}\n")
    out.write("\n—— 全部改名 ——\n")
    for entity, kind, old, new in planned:
        out.write(f"{kind}\t{entity.identity}\t{entity.name}\t{old}\t{new}\n")
    out.write(f"\n改动文件: {len(changed)}\n")
    out.write("模式: " + ("已写回" if args.apply else "预演") + "\n")
    out.flush()

    print(f"改名 {len(planned)} 处（计量 {per_kind['计量']}，状态 {per_kind['状态']}）；"
          f"改动文件 {len(changed)}；详见 {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
