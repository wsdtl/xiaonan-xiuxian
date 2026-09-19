"""构筑分值：给玩家创造的功法打分，判断是否超纲。

## 定位

**预算闸门，不是强度判定。** 它回答「这门功法是否明显超纲」，不回答「这门功法实际多强」。
真实强度用 `tools/强度对照.py` 打真实对局测。

## 系统自带的不判分

存量 600 门功法不受分值约束，它们只做一件事：**标定这份表**。校准后的动作分值写进
`tools/数据/构筑分值表.json`，并整体缩放使存量得分的中位数**恰好等于预算总分**。
于是「预算 = 存量中位数」这句话是可复算的，不是我拍的数字。

## 公式

    得分 = 结构调整 × Σ(动作基础分) + Σ(数值规模分)

- 动作基础分：`10 / √(该动作在存量中的出现次数)` —— 越稀有的机制越贵
- 数值规模分：`0.5 * log10(1 + 数值 / 中位数) * 10 * 权重` —— 相对规模，非绝对值
- 结构调整：`2 ** (|机制动作种数 - 中位数| / 2)` —— 越复杂越贵，过简也略贵

## 用法

```powershell
# 只看存量分布与中位数（只读）
.venv/Scripts/python.exe -X utf8 tools/构筑分值.py

# 校准：把动作分值写回分值表（会改 tools/数据/构筑分值表.json）
.venv/Scripts/python.exe -X utf8 tools/构筑分值.py --校准
```

**退出码：0 = 正常；2 = 存量读不到或公式失效。**
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _path in (str(ROOT), str(ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

#: 分值表放在 `tools/数据/` 而不是 `data/`：它是**工具侧的标定产物**（由
#: `tools/构筑分值.py --校准` 写回），不是游戏内容。放在 `data/` 里会被
#: 「取回基线原文」的 `git checkout -- data` 静默删掉——实测踩过一次，
#: 表现是所有通道都报「数据文件没有匹配的读取规则」。
SCORE_FILE = ROOT / "tools" / "数据" / "构筑分值表.json"
GONGFA_DIR = ROOT / "data" / "战斗" / "内容" / "功法"

#: 取数/选目标的管道动作，不算机制——它们不体现设计意图，每个节点都可能有。
PIPELINE_ABILITIES = frozenset({
    "选择目标", "选择状态", "选择技能", "读取数值",
    "数值条件", "概率条件", "状态条件", "类型条件", "组合条件", "标签条件",
})

ABILITY = "能力"


def load_table() -> dict:
    return json.loads(SCORE_FILE.read_text(encoding="utf-8"))


def action_kinds(tree: object) -> list[str]:
    """一门功法用到的机制动作（去重、保持出现顺序）。"""

    from game.core.combat.templates import _ability_sequence

    seen: list[str] = []
    for ability in _ability_sequence(tree):
        if ability in PIPELINE_ABILITIES or ability in seen:
            continue
        seen.append(ability)
    return seen


def numeric_fields(tree: object, spec: dict) -> dict[str, list[float]]:
    """按分值表登记的计数字段，收集这门功法里的所有取值。"""

    found: dict[str, list[float]] = collections.defaultdict(list)

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in spec and isinstance(value, (int, float)) and not isinstance(value, bool):
                    found[key].append(float(value))
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(tree)
    return found


def numeric_score(found: dict[str, list[float]], spec: dict) -> float:
    """数值规模分：相对该字段中位数的规模，取对数后按权重求和。"""

    total = 0.0
    for key, values in found.items():
        rule = spec.get(key)
        if not rule:
            continue
        mid = float(rule.get("中位数") or 1) or 1.0
        weight = float(rule.get("权重") or 0)
        for value in values:
            total += 0.5 * math.log10(1 + value / mid) * 10 * weight
    return total


def score_card(tree: object, table: dict) -> dict[str, float]:
    """给一张卡打分，返回分项。"""

    kinds = action_kinds(tree)
    costs = table.get("动作分值") or {}
    base = sum(float(costs.get(kind) or 0) for kind in kinds)
    mid_kinds = int((table.get("形状基准") or {}).get("机制动作种数") or 1)
    # 结构调整要**压平**：`2 ** (|差| / 2)` 会让 24 种动作的卡比 17 种的贵 8 倍，
    # 而实测一门功法用 15~24 种动作，强度差不可能有这个量级（分项诊断见工具文档）。
    # 改用 `/ 8`：差 6 种只放大 1.68 倍，与「复杂一点，贵一点」相符。
    adjust = 2 ** (abs(len(kinds) - mid_kinds) / 8)
    numbers = numeric_score(numeric_fields(tree, table.get("计数字段") or {}), table.get("计数字段") or {})
    return {"动作": base, "结构": adjust, "数值": numbers, "合计": adjust * base + numbers}


def corpus_cards() -> list[dict]:
    """读出存量功法（迁移态：卡里是模板引用，需要先展开）。"""

    from game.core.combat.template_data import library
    from game.core.combat.templates import expand_in_place

    lib = library()
    cards: list[dict] = []
    for path in sorted(GONGFA_DIR.glob("功法-*.json")):
        for card in json.loads(path.read_text(encoding="utf-8")):
            expand_in_place(card, lib)
            cards.append(card)
    return cards


def calibrate(cards: list[dict], table: dict) -> dict:
    """用存量反推动作分值，并整体缩放使中位数等于预算总分。

    动作分值只由**出现次数**决定（`10/√次数`），不用任何手写权重——
    这样校准结果完全由存量决定，可复算、可审查。
    """

    counts: collections.Counter = collections.Counter()
    kind_counts: list[int] = []
    for card in cards:
        kinds = action_kinds(card)
        kind_counts.append(len(kinds))
        for kind in kinds:
            counts[kind] += 1

    mid_kinds = int(statistics.median(kind_counts)) or 1
    raw_costs = {
        kind: 10.0 / math.sqrt(count) for kind, count in sorted(counts.items())
    }
    table = dict(table)
    table["动作分值"] = {k: round(v, 4) for k, v in raw_costs.items()}
    table["形状基准"] = {"机制动作种数": mid_kinds}

    scores = [score_card(card, table)["合计"] for card in cards]
    mid_score = statistics.median(scores)
    budget = float((table.get("预算") or {}).get("总分") or 100)
    # 整体缩放：让存量中位数恰好等于预算总分。分值的**相对**大小不变。
    scale = budget / mid_score if mid_score else 1.0
    table["动作分值"] = {k: round(v * scale, 4) for k, v in raw_costs.items()}
    table["计数字段"] = {
        k: dict(v, 权重=round(float(v.get("权重") or 0) * scale, 4))
        for k, v in (table.get("计数字段") or {}).items()
    }
    table["校准"] = {
        "样本": len(cards),
        "机制动作种数中位": mid_kinds,
        "存量得分中位（缩放前）": round(mid_score, 2),
        "缩放系数": round(scale, 6),
        "动作种类": len(counts),
    }
    return table


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--校准", action="store_true", help="把校准结果写回分值表")
    args = parser.parse_args()

    table = load_table()
    cards = corpus_cards()
    if not cards:
        print("读不到存量功法")
        return 2

    calibrated = calibrate(cards, table)
    info = calibrated["校准"]
    print("存量功法 %d 门；机制动作 %d 种，每门用到的种数中位 %d"
          % (info["样本"], info["动作种类"], info["机制动作种数中位"]))

    scores = [score_card(card, calibrated)["合计"] for card in cards]
    quantiles = statistics.quantiles(scores, n=10)
    print("得分分布：最小 %.1f · 10%% %.1f · 中位 %.1f · 90%% %.1f · 最大 %.1f"
          % (min(scores), quantiles[0], statistics.median(scores), quantiles[8], max(scores)))
    print("预算总分 %.0f（= 存量中位数，缩放系数 %.4f）"
          % (calibrated["预算"]["总分"], info["缩放系数"]))

    over = sum(1 for s in scores if s > calibrated["预算"]["总分"])
    print("存量中超过预算的：%d 门（%.0f%%）——它们不判分，只是分布参考"
          % (over, over * 100.0 / len(scores)))

    if not args.校准:
        print("（试运行，未写盘）")
        return 0
    SCORE_FILE.write_text(
        json.dumps(calibrated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"已写回 {SCORE_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
