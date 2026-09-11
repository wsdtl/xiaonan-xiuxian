"""给 13 枚被摘空监听的战丹补回规则，并补上结算出口。

`清惰性节点.py` 摘掉「只写没人读的计量、只加没载荷的状态」时，这 13 枚战丹的
**整条监听被级联摘空**，现在一条规则都没有。它们不是坏，是空。

补法两步：

1. **恢复原监听**：从 `清惰性节点` 执行前的备份里取回 `使用效果.监听` 原文；
2. **补结算出口**：原监听只写计量不读，光恢复又会变回空钩子。所以再挂一条监听，
   读它积累的主计量，按 `主计量 × 8` 恢复血气，然后清零——计量这才有了去处。

**这是补内容、会改平衡**（原来这些丹等于不带规则）。判据：差异必须全部落在这 13 枚里。

    python tools/一次性迁移/补空规则战丹.py            # 预演
    python tools/一次性迁移/补空规则战丹.py --apply
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: 执行 `清惰性节点.py` 之前的那份数据，原监听从它取。
BACKUP = pathlib.Path(
    r"C:\Users\DengXiaonan\Desktop\_晓楠修仙_重构备份\20260911-182043-清惰性前\data"
)

#: 被摘空监听的 13 枚战丹。
EMPTY = [
    "120034", "120036", "120037", "120041", "120046", "120051", "120060",
    "120068", "120071", "120076", "120109", "120111", "120157",
]

#: 结算出口的倍率：每层主计量恢复多少点血气。
PER_STACK = 8


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rename = _load("词条改名", "tools/一次性迁移/重命名词条.py")


def backup_pill(identity: str) -> dict | None:
    for path in sorted(BACKUP.glob("炼丹/内容/丹药/战丹/*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            if str(entry["编号"]) == identity:
                return entry
    return None


def written_counters(listeners) -> list[str]:
    """原监听里写过的计量，按出现次数排序。"""

    counts: dict[str, int] = {}
    for node in rename.walk(listeners):
        if node.get("能力") == "修改构筑计量":
            name = node.get("计量")
            if isinstance(name, str):
                counts[name] = counts.get(name, 0) + 1
    return [name for name, _ in sorted(counts.items(), key=lambda kv: -kv[1])]


def payoff(counter: str) -> dict:
    """读主计量、按层恢复血气、然后清零。"""

    read = {
        "能力": "读取数值",
        "来源": "构筑计量",
        "计量": counter,
        "目标": {"能力": "选择目标", "范围": "自身"},
    }
    return {
        "能力": "监听事件",
        "事件": "行动结束",
        "观察角色": "行动者",
        "阵营关系": "自身",
        "每次行动最多触发": 1,
        "条件": [
            {
                "能力": "数值条件",
                "左值": dict(read),
                "比较": "大于等于",
                "右值": 3,
            }
        ],
        "效果": [
            {
                "能力": "恢复资源",
                "目标": {"能力": "选择目标", "范围": "自身"},
                "资源": "血气",
                "数值": {
                    "能力": "计算数值",
                    "方式": "相乘",
                    "左值": dict(read),
                    "右值": PER_STACK,
                },
            },
            {
                "能力": "修改构筑计量",
                "目标": {"能力": "选择目标", "范围": "自身"},
                "计量": counter,
                "方式": "清空",
                "数值": 0,
                "最高值": 100,
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写回数据文件")
    parser.add_argument("--报告", dest="report", default="_补空规则战丹.txt")
    args = parser.parse_args()

    entities = rename.load_entities()
    rows: list[str] = []
    for entity in entities:
        if entity.identity not in EMPTY:
            continue
        original = backup_pill(entity.identity)
        if original is None:
            rows.append(f"{entity.identity}\t{entity.name}\t备份里没有\t—")
            continue
        listeners = list((original.get("使用效果") or {}).get("监听") or [])
        counters = written_counters(listeners)
        effect = entity.payload.setdefault("使用效果", {})
        effect["监听"] = listeners
        if counters:
            listeners.append(payoff(counters[0]))
            rows.append(
                f"{entity.identity}\t{entity.name}\t恢复 {len(listeners) - 1} 条监听"
                f"\t主计量 {counters[0]}\t+ 结算出口"
            )
        else:
            rows.append(f"{entity.identity}\t{entity.name}\t恢复 {len(listeners)} 条监听\t无计量\t未补出口")

    changed = rename.write_back(entities) if args.apply else []

    out = io.TextIOWrapper(open(ROOT / args.report, "wb"), encoding="utf-8")
    out.write(f"目标 {len(EMPTY)} 枚；改动文件 {len(changed)}\n")
    out.write("模式: " + ("已写回" if args.apply else "预演") + "\n\n")
    out.write("编号\t名称\t恢复\t主计量\t出口\n")
    for line in rows:
        out.write(line + "\n")
    out.flush()

    print(f"目标 {len(EMPTY)} 枚；改动文件 {len(changed)}；详见 {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
