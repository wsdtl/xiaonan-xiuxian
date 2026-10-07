"""把四类卡片的规则正文渲染出来，供人审阅，并报出渲染器认不出的节点。

渲染规则见 `data/战斗/内容/文本规范.md`。本工具只读数据，不改任何文件：

    .venv/Scripts/python.exe -X utf8 tools/渲染战斗文本.py
    .venv/Scripts/python.exe -X utf8 tools/渲染战斗文本.py --卡片 400541
    .venv/Scripts/python.exe -X utf8 tools/渲染战斗文本.py --体裁 功法 --报告 _输出/功法说明.md

输出：

* `<报告>` —— 每张卡的「现有说明」与「渲染正文」左右对照（默认 `_输出/战斗文本预览.md`）；
* 标准输出 —— 认不出的原子能力、事件、字段清单；有未支持项即退出码 1。

**读数据必须走 `构筑模板展开`**：卡里的效果已经模板化，直接 `json.loads` 拿到的是
`{"模板": …}` 引用，渲染出来全是 `〈未支持：〉`（实测整套功法都这样）。
"""

from __future__ import annotations

import pathlib as _pathlib
import sys as _sys

# 共用库住在 tools/库/：脚本按文件运行时 sys.path[0] 是自己的目录，得手动加。
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1] / "库"))

import argparse
import collections
import io
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from game.core.combat.card_text import render_body, render_listeners  # noqa: E402
from 构筑模板展开 import load_build_json as _load_build_json  # noqa: E402
from 规则层 import load_rule_layer  # noqa: E402

DATA = ROOT / "data"
SURFACES = (
    ("功法", "战斗/内容/功法/功法-*.json"),
    ("真意", "战斗/内容/真意/真意-*.json"),
    ("气机", "战斗/内容/气机/气机-*.json"),
    ("器律", "物品/炼器/内容/器律-*.json"),
    ("战场环境", "战斗/内容/战场环境/*.json"),
    ("战丹", "物品/炼丹/内容/丹药/战丹/*.json"),
    ("长期伤势", "角色/内容/伤势.json"),
)


def cards(pattern: str):
    for path in sorted(DATA.glob(pattern)):
        document = _load_build_json(path)
        entries = document if isinstance(document, list) else [document]
        for entry in entries:
            if isinstance(entry, dict):
                yield entry


def _fingerprint(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def defects(card: dict) -> list[str]:
    """卡内数据的冗余形态；渲染器只转写，这些要回到 JSON 里修。

    只报**确实冗余**的：`条件执行` 套一层同条件的判定。`尝试执行` 的成败分支同内容
    看着冗余，其实是引擎里唯一能表达「无论成败都做某事」的写法（`_run_effects` 短路
    返回），不算缺陷——渲染器会把它收成一句「然后无论成败，…」。
    """

    found: list[str] = []
    name = card.get("名称")

    def walk(node, conditions: tuple[str, ...]):
        if isinstance(node, dict):
            if node.get("能力") == "条件执行":
                stamp = _fingerprint(node.get("条件"))
                if stamp in conditions:
                    found.append(f"{name}：条件执行套了同一组条件")
                walk(node.get("成立效果"), conditions + (stamp,))
                walk(node.get("不成立效果"), conditions + (stamp,))
                return
            for value in node.values():
                walk(value, conditions)
        elif isinstance(node, list):
            for value in node:
                walk(value, conditions)

    walk(card, ())
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--卡片", action="append", default=[], help="只渲染这些编号")
    parser.add_argument("--体裁", action="append", default=[],
                        help="只渲染这些体裁（功法 / 真意 / 气机 / 器律 / 战场环境 / 战丹 / 长期伤势）")
    parser.add_argument("--报告", dest="report", default="_输出/战斗文本预览.md")
    args = parser.parse_args()

    wanted = set(args.卡片)
    kinds = set(args.体裁)
    未知体裁 = kinds - {name for name, _ in SURFACES}
    if 未知体裁:
        print(f"未登记的体裁：{'、'.join(sorted(未知体裁))}")
        return 2
    (ROOT / "_输出").mkdir(exist_ok=True)
    out = io.TextIOWrapper(open(ROOT / args.report, "wb"), encoding="utf-8")
    unknown: collections.Counter[str] = collections.Counter()
    issues: collections.Counter[str] = collections.Counter()
    total = 0
    empty = 0

    for section, pattern in SURFACES:
        if kinds and section not in kinds:
            continue
        for card in cards(pattern):
            identity = str(card.get("编号"))
            if wanted and identity not in wanted:
                continue
            total += 1
            lines, misses = render_body(card, load_rule_layer())
            # 长期伤势的规则挂在 `战斗状态.监听` 上，体裁与卡片不同，单独走一条。
            if not lines:
                state = card.get("战斗状态")
                if isinstance(state, dict) and state.get("监听"):
                    lines, misses = render_listeners(state)
            for miss in misses:
                unknown[miss] += 1
            for issue in defects(card):
                issues[issue.split("：", 1)[1]] += 1
            if not lines:
                empty += 1
            out.write(f"\n## {section} {identity} {card.get('名称')}\n\n")
            out.write("```text\n")
            out.write("【现有说明】\n")
            out.write(str(card.get("说明") or "").rstrip() + "\n\n")
            out.write("【渲染正文】\n")
            out.write("\n".join(lines) if lines else "（空）")
            out.write("\n```\n")

    out.write(f"\n---\n\n共 {total} 个实体，正文为空 {empty} 个。\n")
    if issues:
        out.write(f"卡内数据缺陷 {sum(issues.values())} 处：\n")
        for issue, count in issues.most_common():
            out.write(f"  {count:>5}  {issue}\n")
    out.flush()

    if issues:
        print(f"卡内数据缺陷 {sum(issues.values())} 处：")
        for issue, count in issues.most_common():
            print(f"  {count:>5}  {issue}")
    if unknown:
        print(f"渲染器认不出的 {len(unknown)} 类节点：")
        for miss, count in unknown.most_common(40):
            print(f"  {count:>5}  {miss}")
        print(f"详见 {args.report}")
        return 1
    print(f"全部 {total} 个实体都能完整渲染，无未支持节点。详见 {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
