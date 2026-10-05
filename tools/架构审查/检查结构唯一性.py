"""结构唯一性清点：一卡一结构、两两不重样（双口径）。

口径甲（严格 · 原子能力组合）：只取卡片各能力下的「效果」树做签名；
口径乙（构筑）：整卡去掉 名称 / 编号 / 说明 后做签名（含属性构成、权重、释放顺序、精神消耗、冷却行动等构筑字段）。

两段读数都写进 tools/基准/结构唯一性基线.json；任一口径的唯一数低于基线即红。

退出码：0 = 均不低于基线；1 = 有低于基线；2 = 基线缺失或数据读取失败。
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTENT_ROOT = ROOT / "data/战斗/内容"
BASELINE = ROOT / "tools/基准/结构唯一性基线.json"
SECTIONS = ("功法", "真意", "气机")


def measure_section(section: str) -> dict:
    strict: collections.Counter = collections.Counter()
    whole_card: collections.Counter = collections.Counter()
    for p in sorted((CONTENT_ROOT / section).rglob("*.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        for c in (doc if isinstance(doc, list) else [doc]):
            if not isinstance(c, dict):
                continue
            效 = [e for a in (c.get("能力") or []) if isinstance(a, dict) and isinstance(a.get("效果"), list) for e in a["效果"]]
            strict[json.dumps(效, sort_keys=True, ensure_ascii=False)] += 1
            纯 = {k: v for k, v in c.items() if k not in ("名称", "编号", "说明")}
            whole_card[json.dumps(纯, sort_keys=True, ensure_ascii=False)] += 1
    return {"卡数": sum(whole_card.values()), "严格唯一": len(strict), "构筑唯一": len(whole_card)}


def main() -> int:
    if not BASELINE.exists():
        print("结构唯一性审查：基线缺失")
        return 2
    基线 = json.loads(BASELINE.read_text(encoding="utf-8")).get("各段", {})
    失败, 读数 = [], []
    for section in SECTIONS:
        v = measure_section(section)
        基线段 = 基线.get(section, {})
        读数.append(f"{section} 严格 {v['严格唯一']} / 构筑 {v['构筑唯一']} / 卡 {v['卡数']}")
        for 键, 名 in (("严格唯一", "严格口径"), ("构筑唯一", "构筑口径")):
            if v[键] < 基线段.get(键, 0):
                失败.append(f"{section}：{名}唯一 {v[键]} 低于基线 {基线段.get(键, 0)}")
    print("结构唯一性：" + " ｜ ".join(读数))
    if 失败:
        for f in 失败:
            print("  [失败] " + f)
        return 1
    print("  一卡一结构、两两不重样：两个口径均不低于基线")
    return 0


if __name__ == "__main__":
    sys.exit(main())
