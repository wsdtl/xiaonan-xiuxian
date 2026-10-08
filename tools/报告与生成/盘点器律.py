"""器律盘点：把这次重做的现状一条命令重算出来——阶梯、覆盖、每条签名与强度画像。

为什么不落一份静态基线文件：器律 64 条已经全部**内联**（不再引用构筑模板），
现状完全由 `data/物品/炼器/内容/器律-*.json` 决定；任何一份抄下来的表格都会在某次改动后烂掉。
所以这里的做法是**可重算**：读数一律现算，要看就重跑，不存在过期问题。

盘四样：

1. **器阶阶梯**——顺序与档位强度只在 `规则/器则.json` 声明一处（装载期由炼器核心校验）；
2. **覆盖矩阵**——8 个用途 × 4 个可用器阶，每格 2 条；
3. **每条签名**——事件集合 / 消费方式 / 产出集合（同用途内两两不同，就是「不是同一模板换名换参」）；
   消费方式只取真正改动数值的那几个能力的 `方式`，`计算数值` 的算法名不算；
4. **强度画像**——按器阶统计可缩放字段（威力倍率 / 数值 / 层数 / 最高值）与触发上限的分布。

判定不在这里：阶梯自洽、倍率单调、强度出口、两两不等这些由 `tools/架构审查/检查器律形状.py` 守。
本脚本只报现状，退出码恒为 0。

    .venv/Scripts/python.exe -X utf8 tools/报告与生成/盘点器律.py            # 打到标准输出
    .venv/Scripts/python.exe -X utf8 tools/报告与生成/盘点器律.py --输出 _输出/器律盘点.md
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
RECIPE = ROOT / "data" / "物品" / "炼器" / "规则" / "器则.json"
LAWS = ROOT / "data" / "物品" / "炼器" / "内容"
#: 产出类原子能力：判「同模板换参」的三样之一。
#: 真正的「消费/改动方式」只出现在这些能力上；`计算数值`/`条件执行` 的 `方式` 是算法，不算消费口径。
MUTATORS = ("修改状态层数", "修改构筑计量", "修改行动条", "修改技能冷却", "修改事件标签")
VERBS = ("追加攻击", "造成伤害", "触发技能", "恢复资源", "添加状态", "移除状态",
         "修改行动条", "修改技能冷却", "复制技能", "修改事件标签")
SCALABLE = ("威力倍率", "数值", "层数", "最高值")


def _walk(node, sink: list[dict]) -> None:
    if isinstance(node, dict):
        sink.append(node)
        for value in node.values():
            _walk(value, sink)
    elif isinstance(node, list):
        for value in node:
            _walk(value, sink)


def _signature(nodes: list[dict]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    events = tuple(sorted({str(n.get("事件")) for n in nodes if n.get("能力") == "监听事件"}))
    ways = tuple(sorted({str(n.get("方式")) for n in nodes if n.get("能力") in MUTATORS and n.get("方式") is not None}))
    verbs = tuple(sorted({str(n.get("能力")) for n in nodes if n.get("能力") in VERBS}))
    return events, ways, verbs


def _laws() -> list[tuple[str, dict, list[dict]]]:
    rows: list[tuple[str, dict, list[dict]]] = []
    for path in sorted(LAWS.glob("器律-*.json")):
        use = path.stem[3:]
        for entry in json.loads(path.read_text(encoding="utf-8")):
            nodes: list[dict] = []
            _walk(entry.get("能力"), nodes)
            rows.append((use, entry, nodes))
    return rows


def _ladder() -> list[str]:
    data = json.loads(RECIPE.read_text(encoding="utf-8"))
    lines = ["器阶阶梯（声明处：data/物品/炼器/规则/器则.json）",
             "  名称      阶序  器律能力倍率  等级范围   开放器律孔"]
    for row in data["器阶"]:
        span = row["等级范围"]
        lines.append("  %-6s  %4s  %10s  %4s-%-4s  %s" % (
            row["名称"], row["阶序"], row["器律能力倍率"], span[0], span[1], row["开放器律孔"]))
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--输出", default="", help="写进文件；默认打到标准输出")
    args = parser.parse_args()

    rows = _laws()
    out: list[str] = ["# 器律盘点", ""]
    out += _ladder()
    out += ["", "覆盖矩阵（用途 × 器阶，条数）"]
    matrix: dict[str, dict[str, int]] = collections.defaultdict(dict)
    for use, entry, _ in rows:
        matrix[use][entry["器阶"]] = matrix[use].get(entry["器阶"], 0) + 1
    tiers = [row["名称"] for row in json.loads(RECIPE.read_text(encoding="utf-8"))["器阶"]]
    usable = [t for t in tiers if matrix and t in {e["器阶"] for _, e, _ in rows}]
    out.append("  用途    " + "  ".join(f"{t}" for t in usable) + "   合计")
    for use in sorted(matrix):
        counts = [matrix[use].get(t, 0) for t in usable]
        out.append("  %-6s  %s   %d" % (use, "  ".join(str(c) for c in counts), sum(counts)))
    out.append("  合计    " + "  ".join(str(sum(matrix[u].get(t, 0) for u in matrix)) for t in usable)
               + "   %d" % len(rows))

    signatures = collections.Counter()
    for use, _, nodes in rows:
        signatures[(use,) + _signature(nodes)] += 1
    repeated = {k: v for k, v in signatures.items() if v > 1}
    out += ["", "每条签名（用途 + 事件集合 + 消费方式 + 产出集合）",
            "  不同组合 %d / 共 %d 条；重复组合 %d 组" % (len(signatures), len(rows), len(repeated))]
    for use, entry, nodes in rows:
        events, ways, verbs = _signature(nodes)
        limits = sorted({str(n.get("每次行动最多触发")) for n in nodes
                         if n.get("能力") == "监听事件" and n.get("每次行动最多触发") is not None})
        out.append("  %s %-6s %-5s 事件[%s] 方式[%s] 产出[%s] 限额[%s]" % (
            entry["编号"], entry["名称"][:6], entry["器阶"],
            "/".join(events), "/".join(ways) or "无", "/".join(verbs), "/".join(limits)))

    out += ["", "强度画像（按器阶统计可缩放字段与触发上限）"]
    profile: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for _, entry, nodes in rows:
        bucket = profile[entry["器阶"]]
        for key in SCALABLE:
            bucket[key] += sum(1 for n in nodes if key in n)
        bucket["监听节点"] += sum(1 for n in nodes if n.get("能力") == "监听事件")
    for tier in usable:
        bucket = profile[tier]
        out.append("  %-6s %s" % (tier, "  ".join(f"{k} {bucket[k]}" for k in (*SCALABLE, "监听节点"))))

    text = chr(10).join(out) + chr(10)
    if args.输出:
        path = pathlib.Path(args.输出)
        if not path.is_absolute():
            path = ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"已写入 {path}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
