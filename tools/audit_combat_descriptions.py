"""Audit combat content descriptions against their JSON ability surface."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ("功法", "真意", "气机", "器律")


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
                table = entity.get("词条") if isinstance(entity.get("词条"), dict) else {}
                description = str(entity.get("说明", ""))
                if not description.strip():
                    errors.append(f"{category}/{name}: 缺少说明")
                    continue
                if category == "功法":
                    for section in ("主动：", "被动：", "裁定："):
                        if section not in description:
                            errors.append(f"{category}/{name}: 缺少{section}")
                    if "裁定：" in description:
                        rulings = description.split("裁定：", 1)[1]
                missing = sorted(
                    ability for ability in _abilities(entity)
                    if ability.rsplit("·", 1)[-1] not in description
                    and ability not in description
                )
                for ability in missing:
                    errors.append(f"{category}/{name}: 说明未覆盖能力 {ability}")
    return errors


def main() -> int:
    errors = audit(ROOT)
    if errors:
        print(f"战斗说明审查失败：{len(errors)} 项")
        print("\n".join(errors[:200]))
        return 1
    print("战斗说明审查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
