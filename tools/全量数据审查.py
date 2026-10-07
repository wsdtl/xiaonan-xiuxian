"""全量正式 JSON 审查报告；不参与游戏运行时。"""

from __future__ import annotations

import argparse
import json
import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game.core.data import JsonDataService


def audit(root: Path) -> dict[str, object]:
    service = JsonDataService(root)
    status = service.initialize()
    sections: dict[str, int] = {}
    missing_name: dict[str, int] = {}
    weighted: dict[str, int] = {}
    invalid_weight: list[str] = []
    all_ids = {record.entity_id for record in service.numbered_entities()}
    unresolved_refs: list[str] = []
    missing_fields: dict[str, dict[str, int]] = {}
    required_by_section = {
        "功法": ("名称", "说明", "能力", "属性构成", "权重"),
        "真意": ("名称", "说明", "能力", "属性构成", "权重"),
        "气机": ("名称", "说明", "能力", "属性构成", "权重"),
        "道侣": ("名称", "说明"),
    }
    for record in service.numbered_entities():
        sections[record.section] = sections.get(record.section, 0) + 1
        value = record.value
        for ref in _six_digit_values(value):
            if ref not in all_ids:
                unresolved_refs.append(f"{record.section}:{record.entity_id}->{ref}")
        required = required_by_section.get(record.section, ())
        for field in required:
            if field not in value or value[field] in (None, "", [], {}):
                section_missing = missing_fields.setdefault(record.section, {})
                section_missing[field] = section_missing.get(field, 0) + 1
        if not str(value.get("名称", "")).strip():
            missing_name[record.section] = missing_name.get(record.section, 0) + 1
        if "权重" in value:
            weighted[record.section] = weighted.get(record.section, 0) + 1
            weight = value["权重"]
            if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
                invalid_weight.append(f"{record.section}:{record.entity_id}")
    pool_report: dict[str, dict[str, int]] = {}
    for file_id, section in service.pools().items():
        members = service.pool_members((file_id,), section, deduplicate=False)
        unique = len(set(members))
        row = pool_report.setdefault(section, {"pools": 0, "members": 0, "unique_members": 0})
        row["pools"] += 1
        row["members"] += len(members)
        row["unique_members"] += unique
    return {
        "root": str(root.resolve()),
        "documents": status.document_count,
        "content_documents": status.content_document_count,
        "entities": status.entity_count,
        "numbered_entities": len(service.numbered_entities()),
        "pools": status.pool_count,
        "sections": dict(sorted(sections.items())),
        "missing_name": dict(sorted(missing_name.items())),
        "weighted_sections": dict(sorted(weighted.items())),
        "invalid_weight": invalid_weight,
        "unresolved_six_digit_references": unresolved_refs,
        "missing_fields": {
            section: dict(sorted(fields.items()))
            for section, fields in sorted(missing_fields.items())
        },
        "pools_by_section": dict(sorted(pool_report.items())),
        "document_paths": len(service.document_paths()),
    }


def _six_digit_values(value: object) -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(value, dict):
        for child in value.values():
            found.extend(_six_digit_values(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            found.extend(_six_digit_values(child))
    elif isinstance(value, str):
        found.extend(re.findall(r"(?<!\d)\d{6}(?!\d)", value))
    return tuple(found)


def main() -> int:
    parser = argparse.ArgumentParser(description="审查正式 JSON 数据")
    parser.add_argument("--data", type=Path, default=Path(__file__).parents[1] / "data")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    report = audit(args.data)
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"JSON 数据审查通过：{report['documents']} documents, {report['entities']} entities, {report['pools']} pools")
        for section, count in report["sections"].items():
            print(f"  {section}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
