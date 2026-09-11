"""Audit battle-card descriptions against their JSON ability surface.

规则正文已经改由 `game/core/combat/card_text.py` 从能力树渲染，`查看` 现算现显示。
所以这里不再检查「说明有没有覆盖每个能力」——那件事现在由渲染器保证，覆盖检查见
`tools/渲染战斗文本.py`（认不出的节点会直接失败）。

本审查留下来管另外两件事：

1. `说明` 只许放卡头。正文一旦被写回 JSON，就又变成第二事实源，会漂移。
2. 占位残句与空说明仍然必须报错——它们是玩家真的会读到的字。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ("功法", "真意", "气机", "器律")
#: 生成器留下的占位残句；它会被玩家当成规则读，所以必须当错误报出来。
PLACEHOLDER = "按 JSON 能力执行"
#: 规则正文的起始行。它出现在 `说明` 里就说明正文被写回数据了。
SECTION = re.compile(r"^(?:主动|被动|裁定|常驻|闭环结算)\s*[:：]", re.MULTILINE)


def _iter_json(root: Path):
    for path in root.rglob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, list):
            yield path, value


def _abilities(entity: dict) -> set[str]:
    return {
        str(item.get("名称", "")).strip()
        for item in entity.get("能力", [])
        if isinstance(item, dict) and item.get("名称")
    }


def audit(root: Path) -> list[str]:
    errors: list[str] = []
    global_names: dict[str, str] = {}
    for category in CONTENT:
        base = root / "data" / "战斗" / "内容" / category
        for path, values in _iter_json(base):
            for entity in values:
                if not isinstance(entity, dict):
                    continue
                name = str(entity.get("名称", path.stem))
                for ability in _abilities(entity):
                    previous = global_names.get(ability)
                    if previous and previous != f"{category}/{name}":
                        errors.append(f"全局能力名称重复：{ability} -> {previous}、{category}/{name}")
                    global_names[ability] = f"{category}/{name}"
                description = str(entity.get("说明", ""))
                if not description.strip():
                    errors.append(f"{category}/{name}: 缺少说明")
                    continue
                if PLACEHOLDER in description:
                    errors.append(f"{category}/{name}: 说明含占位残句「{PLACEHOLDER}」")
                if SECTION.search(description):
                    errors.append(
                        f"{category}/{name}: 说明里写了规则正文；正文由渲染器现算，"
                        "存储的正文会漂移（跑 tools/一次性迁移/裁掉规则正文.py）"
                    )
    return errors


def main() -> int:
    errors = audit(ROOT)
    if errors:
        print(f"战斗说明审查失败：{len(errors)} 项")
        print("\n".join(errors[:200]))
        return 1
    print("战斗说明审查通过：说明只含卡头，规则正文由渲染器现算")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
