# -*- coding: utf-8 -*-
"""功法常驻属性的形状判据：一张功法卡只许一个常驻块。

设计原则（委托方定的）：常驻属性要「分散开、每个功法集中」。
一本功法只加同一类的属性，六本合起来才覆盖流派的完整属性面。
如果一张卡能塞多个常驻块，就会出现「万能功法」，泛用性收不住。

判据检查：功法卡的根能力里， 固定属性加成 最多出现一次。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/战斗/检查常驻属性.py

退出码：0 = 合规，1 = 有功法写了多个常驻块。
"""
from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[3]
DATA = ROOT / "data" / "战斗" / "内容" / "功法"


def main() -> int:
    problems = []
    total = 0
    for path in sorted(DATA.rglob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        cards = value if isinstance(value, list) else [value]
        for card in cards:
            if not isinstance(card, dict):
                continue
            total += 1
            roots = card.get("能力") or []
            count = sum(1 for node in roots if isinstance(node, dict) and node.get("能力") == "固定属性加成")
            if count > 1:
                problems.append(f"{path.name}：{count} 个常驻块")
    if problems:
        print("功法常驻属性超过一个：")
        for item in problems:
            print("  " + item)
        print()
        print("每本功法只许一个常驻块：集中加一类属性，六本合起来才覆盖流派。")
        return 1
    print(f"常驻属性审查通过：{total} 张功法卡，每张最多一个常驻块")
    return 0


if __name__ == "__main__":
    sys.exit(main())