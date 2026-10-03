"""真意边界判据（只按目标要求，不夹带自创规则）。

目标里对真意只有三条要求：
  一、**只做被动**：不得出现 `主动技能`，也不得占行动（`冷却行动` / `释放顺序`）
  二、**不玩计数**：`修改构筑计量` 占比 ≤10%（真意不该被计数器统治）
  三、**说明只留卡头短句**：说明长度 ≤60 字符

（原先我自创的"48 类分布 / 命名规则"不在目标里，已经删除，避免画蛇添足。）

跑法：`python -X utf8 tools/架构审查/检查真意机制.py`
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
ARTS = ROOT / "data" / "战斗" / "内容" / "真意"
COUNTER_QUOTA = 0.10
TEXT_LIMIT = 60


def main() -> int:
    from game.core.combat.template_data import TEMPLATE_CLUSTERS

    cards: list[dict] = []
    for path in sorted(ARTS.rglob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict):
                cards.append(item)

    usage: collections.Counter[str] = collections.Counter()
    active: list[str] = []
    too_long: list[str] = []
    for card in cards:
        title = str(card.get("名称") or "")
        abilities: set[str] = set()

        def walk(node: object) -> None:
            if isinstance(node, dict):
                name = node.get("模板")
                if isinstance(name, str):
                    for ability in (TEMPLATE_CLUSTERS.get(name) or [[]])[0]:
                        abilities.add(str(ability))
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(card)
        usage.update(abilities)
        for node in card.get("能力") or []:
            if isinstance(node, dict) and node.get("能力") != "被动技能":
                active.append(f"{title}：{node.get('能力')}")
            if isinstance(node, dict) and ("冷却行动" in node or "释放顺序" in node):
                active.append(f"{title}：占行动字段")
        if len(str(card.get("说明") or "")) > TEXT_LIMIT:
            too_long.append(title)

    failures = 0
    total = len(cards)
    ok = not active
    failures += not ok
    print(f"[{'通过' if ok else '失败'}] 真意只做被动（不主动、不占行动）：违规 {len(active)} 处 {active[:3]}")
    used = sum(usage.values()) or 1
    share = usage.get("修改构筑计量", 0) / used
    ok = share <= COUNTER_QUOTA
    failures += not ok
    print(f"[{'通过' if ok else '失败'}] 计量占比：{usage.get('修改构筑计量', 0)} / {used}（{share * 100:.1f}%，上限 {COUNTER_QUOTA * 100:.0f}%）")
    ok = not too_long
    failures += not ok
    print(f"[{'通过' if ok else '失败'}] 说明 ≤{TEXT_LIMIT} 字：违规 {len(too_long)} 张")
    print(f"真意 {total} 张 ｜ 总账：失败 {failures} 组")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
