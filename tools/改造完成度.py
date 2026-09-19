"""改造完成度：还有多少张卡是「一个模子」，以及空位与标签词表。

改造的目标是「每张卡都能被看出差别」，所以完成度不能只报四个轴的全局占比，
要**落到卡上**：一张卡如果在下面三个维度上都只有一种取值，它就是一整张模子卡。

    触发时点维度：该卡的监听节点用了几种事件
    缩放来源维度：该卡的 `读取数值` 通知了几种来源
    限额维度：该卡的监听节点用了几种 `每次行动最多触发` 取值

顺带报两件按负责人口径要在意的事：**引擎支持但没人用的读取来源**、**主动技能的标签词表**。

    .venv/Scripts/python.exe -X utf8 tools/改造完成度.py            # 总览
    .venv/Scripts/python.exe -X utf8 tools/改造完成度.py --明细     # 再列出卡最集中的文件

**退出码：0 = 正常。**
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from 全库扫描 import 全库来源  # noqa: E402
from 构筑模板展开 import load_build_json as _load_build_json  # noqa: E402
SURFACES = (
    ("功法", "data/战斗/内容/功法/功法-*.json"),
    ("真意", "data/战斗/内容/真意/真意-*.json"),
    ("气机", "data/战斗/内容/气机/气机-*.json"),
    ("器律", "data/物品/炼器/内容/器律-*.json"),
)
CAP_FIELD = "每次行动最多触发"
ENGINE_ORIGINS = tuple(
    json.loads((ROOT / "data/战斗/定义/原子能力.json").read_text(encoding="utf-8"))
    ["读取数值"]["字段"]["来源"]["选项"]
)


def profile(entry: dict) -> dict[str, set]:
    events: set[str] = set()
    sources: set[str] = set()
    caps: set[str] = set()
    tags: set[str] = set()
    listeners = 0

    def walk(node: object) -> None:
        nonlocal listeners
        if isinstance(node, dict):
            ability = str(node.get("能力") or "")
            if ability == "监听事件":
                listeners += 1
                events.add(str(node.get("事件") or ""))
                if CAP_FIELD in node:
                    caps.add(str(node[CAP_FIELD]))
            elif ability == "读取数值":
                sources.add(str(node.get("来源") or "固定值"))
            elif ability == "主动技能":
                value = node.get("标签")
                if isinstance(value, list):
                    for item in value:
                        tags.add(str(item))
            for nested in node.values():
                walk(nested)
        elif isinstance(node, list):
            for nested in node:
                walk(nested)

    walk(entry)
    return {"事件": events, "来源": sources, "限额": caps, "标签": tags, "监听": listeners}


def corpus_origins() -> set[str]:
    """全库（不只四类构筑卡）用到的读取来源。

    空位审计原来只扫 `SOURCES` 那四类卡，于是战丹/伤势/战场环境里用到的来源仍被报成"没人用"
    （`目标当前护盾` 就栽在这上面）。空位说的是**全库**，就得扫全库——而且模板引用
    得先展开，否则 `读取数值` 藏在模板主体里数不到。两件事都在 `全库扫描` 里。
    """

    return 全库来源()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--明细", action="store_true", help="列出模子卡最集中的文件")
    args = parser.parse_args()

    origins: collections.Counter = collections.Counter()
    tag_counter: collections.Counter = collections.Counter()
    collapsed: collections.Counter = collections.Counter()
    per_file: collections.Counter = collections.Counter()
    per_file_total: collections.Counter = collections.Counter()
    total = 0
    rows: list[str] = []

    for section, pattern in SURFACES:
        for path in sorted(ROOT.glob(pattern)):
            # 模板引用先展开：迁移之后一条效果可能只剩 `{"模板": …}`，
            # 不展开就把「这张卡的时点/来源/限额各有几种」数成 1 种。
            for entry in _load_build_json(path):
                total += 1
                info = profile(entry)
                per_file_total[f"{section}/{path.stem}"] += 1
                for name in info["来源"]:
                    origins[name] += 1
                for name in info["标签"]:
                    tag_counter[name] += 1
                if info["监听"] == 0:  # 气机这类纯属性块没有监听节点，不参与「模子卡」判定
                    collapsed["无监听节点（纯属性块）"] += 1
                    continue
                dims = (len(info["事件"]) <= 1, len(info["来源"]) <= 1, len(info["限额"]) <= 1)
                count = sum(dims)
                collapsed[f"三面同模 {count} 个"] += 1
                if count == 3:
                    key = f"{section}/{path.stem}"
                    per_file[key] += 1
                    if len(rows) < 200:
                        rows.append(f"    {key} {entry['编号']}{entry.get('名称')}"
                                    f" 事件{len(info['事件'])} 来源{sorted(info['来源'])}"
                                    f" 限额{sorted(info['限额'])}")

    print(f"卡数 {total}")
    print("\n三面同模（触发时点 / 缩放来源 / 限额取值各只有一种）：")
    for key in ("三面同模 3 个", "三面同模 2 个", "三面同模 1 个", "三面同模 0 个",
                "无监听节点（纯属性块）"):
        if collapsed[key]:
            print(f"  {key:<24}{collapsed[key]:>5} 张  {collapsed[key] / total:>6.1%}")

    # 空位说的是**全库**，所以用 corpus_origins()（四类卡之外还有战丹/伤势/战场环境）。
    used_origins = set(origins) | corpus_origins()
    unused = [name for name in ENGINE_ORIGINS if name not in used_origins]
    print(f"\n空位：引擎支持但全库没人用的读取来源 {len(unused)} 种 —— {' '.join(unused) or '无'}")
    print(f"主动技能标签词表：{len(tag_counter)} 种"
          f" —— {' '.join(f'{k}×{v}' for k, v in tag_counter.most_common(8)) or '无'}")

    if args.明细:
        print("\n三面同模卡最集中的文件：")
        for key, count in per_file.most_common(18):
            print(f"  {key:<22}{count:>4} / {per_file_total[key]:<4} 张")
        print("\n样例：")
        for line in rows[:16]:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
