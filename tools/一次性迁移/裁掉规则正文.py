"""把卡片 `说明` 里的规则正文裁掉，只留卡头。

规则正文现在由 `game/core/combat/card_text.py` 从能力树现算，`说明` 再存一份就是
第二事实源——之前已经漂移过（引用了卡里不存在的专名、占位残句「按 JSON 能力执行」）。
裁掉之后：卡头（风味简介 + 五行）人工写，正文渲染，两边不可能再对不上。

    python tools/一次性迁移/裁掉规则正文.py            # 预演
    python tools/一次性迁移/裁掉规则正文.py --apply
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import io
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIBLING = ROOT / "tools" / "一次性迁移" / "重命名词条.py"

_spec = importlib.util.spec_from_file_location("词条改名", SIBLING)
rename = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rename)

#: 正文起始行。卡头在它之前，之后整段由渲染器负责。
SECTION = re.compile(r"^(?:主动|被动|裁定|常驻|闭环结算)\s*[:：]")


def trim(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines():
        if SECTION.match(line.strip()):
            break
        kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    body = "\n".join(kept).strip()
    return body + "\n" if body else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写回数据文件")
    parser.add_argument("--报告", dest="report", default="_输出/裁掉规则正文.txt")
    args = parser.parse_args()

    entities = rename.load_entities()
    stats: collections.Counter = collections.Counter()
    samples: list[str] = []
    empty: list[str] = []
    chars_before = 0
    chars_after = 0

    for entity in entities:
        text = entity.payload.get("说明")
        if not isinstance(text, str) or not text:
            continue
        trimmed = trim(text)
        chars_before += len(text)
        chars_after += len(trimmed)
        if trimmed == text:
            stats["本来就只有卡头"] += 1
            continue
        stats["裁掉规则正文"] += 1
        if not trimmed:
            empty.append(f"{entity.identity} {entity.name}")
        if len(samples) < 5:
            samples.append(f"{entity.identity} {entity.name}:\n{trimmed.rstrip()}")
        entity.payload["说明"] = trimmed

    changed = rename.write_back(entities) if args.apply else []

    (ROOT / "_输出").mkdir(exist_ok=True)
    out = io.TextIOWrapper(open(ROOT / args.report, "wb"), encoding="utf-8")
    out.write(f"处理实体 {sum(stats.values())}\n")
    for key, count in stats.most_common(6):
        out.write(f"  {count:>6}  {key}\n")
    out.write(
        f"\n说明从 {chars_before:,} 字符裁到 {chars_after:,} 字符"
        f"（净减 {chars_before - chars_after:,}，{(chars_before - chars_after) / max(chars_before, 1):.0%}）\n"
    )
    out.write(f"卡头为空 {len(empty)} 张\n")
    for line in empty[:20]:
        out.write(f"  {line}\n")
    out.write("\n样本:\n")
    for line in samples:
        out.write(f"--- {line}\n")
    out.write(f"\n改动文件: {len(changed)}\n")
    out.write("模式: " + ("已写回" if args.apply else "预演") + "\n")
    out.flush()

    print(
        f"处理 {sum(stats.values())} 个实体；卡头为空 {len(empty)}；"
        f"说明 {chars_before:,} -> {chars_after:,} 字符；"
        f"改动文件 {len(changed)}；详见 {args.report}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
