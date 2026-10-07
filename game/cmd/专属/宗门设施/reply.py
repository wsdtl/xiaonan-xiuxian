"""宗门三座生产建筑的客观旁白回复。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from message import DocumentMessage, M


def page(copy: Mapping[str, Mapping[str, str]], value: Any) -> DocumentMessage:
    common = copy["通用"]
    text = copy[value.facility.name]
    builder = (
        M.document()
        .header(value.facility.name)
        .section(text["场景"], icon="location")
        .line(text["总览"])
        .row((common["职位"], value.role), (common["材料来源"], value.material_source))
        .field(common["宗门灵石"], M.text(value.spirit_stones, tone="cultivation"))
        .section(value.section, icon="item")
    )
    for index, entry in enumerate(value.entries, start=1):
        state = (
            common["已开放"]
            if value.section == "总览"
            else common["可推演"]
            if value.facility.facility_type == "炼阵"
            else common["可炼"]
            if entry.available
            else common["缺材"]
        )
        parts: list[object] = [entry.name]
        if value.facility.facility_type == "炼阵":
            parts.extend((" · ", entry.detail))
        else:
            parts.extend(
                (
                    " · ",
                    M.status(
                        state,
                        tone="positive" if entry.available else "warning",
                    ),
                    " · ",
                    entry.detail,
                )
            )
        if entry.content_id.isdigit() and len(entry.content_id) == 6:
            parts[0] = M.command(
                M.text(entry.name), f"查看 {entry.content_id}"
            )
            parts.extend(
                (" · ", M.command(entry.content_id, f"查看 {entry.content_id}"))
            )
        builder.item(index, *parts)
    if value.page_count > 1:
        builder.small(common["页码"].format_map({"当前页": value.page, "总页数": value.page_count}))
    return builder.build()


def preview(copy: Mapping[str, Mapping[str, str]], value: Any) -> DocumentMessage:
    common = copy["通用"]
    if value.facility.facility_type == "炼器":
        facility_text = copy["百炼堂"]
        assessment = value.assessment
        title = assessment.law.name
        rows = [
            ("器律", assessment.law.law_id),
            ("器阶", assessment.law.stage),
            ("铸法", assessment.law.method),
        ]
        materials = [*assessment.beast_materials, *assessment.mineral_materials]
    elif value.facility.facility_type == "炼丹":
        facility_text = copy["丹鼎阁"]
        assessment = value.assessment
        title = assessment.recipe.medicine_name
        rows = [
            ("丹药", assessment.recipe.recipe_id),
            (
                "成丹",
                f"{assessment.medicine_grade_name}{assessment.recipe.medicine_name}",
            ),
            ("难度", assessment.recipe.difficulty),
            ("炉法", assessment.recipe.method),
        ]
        materials = (
            [assessment.beast_material] if assessment.beast_material else []
        ) + list(assessment.herb_materials)
    else:
        facility_text = copy["演阵台"]
        assessment = value.assessment
        title = assessment.formation.name
        rows = [
            ("阵法", assessment.formation.formation_id),
            ("品级", assessment.grade_name),
            ("阵基", f"承载 {assessment.capacity:g}"),
            ("阵眼", f"冲击 {assessment.impact:g}"),
            ("节点", f"{assessment.nodes}位 · 传导 {assessment.transmission:g}"),
        ]
        materials = list(assessment.materials)
    builder = (
        M.document()
        .header(f"{value.facility.name} · {title}")
        .section(facility_text["审材"], icon="item")
        .row((common["职位"], value.role), (common["材料来源"], value.material_source))
        .section(title, icon="item")
    )
    for label, content in rows:
        builder.field(label, content)
    builder.section("材料", icon="material")
    for index, material in enumerate(materials, start=1):
        if material is None:
            continue
        category = getattr(material, "category", getattr(material, "role", "材料"))
        builder.item(
            index,
            f"{category} · ",
            M.command(
                M.text(material.name),
                f"查看 {material.item_id}",
            ),
            f" × {material.quantity}",
        )
    builder.section("费用", icon="coin")
    builder.field(
        common["灵石消耗"].split("{数量}")[0],
        M.text(value.spirit_stone_cost, tone="warning"),
    )
    builder.small(
        common["个人去向"]
        if value.material_source == "个人纳戒"
        else common["宗门去向"]
    )
    return builder.build()


def completed(copy: Mapping[str, Mapping[str, str]], value: Any) -> DocumentMessage:
    common = copy["通用"]
    text = copy[value.facility.name]
    return (
        M.document()
        .header(f"{value.facility.name} · 炼成")
        .section(text["完成"], icon="item")
        .line(M.status("炼制完成", tone="positive"))
        .row(("产出", value.product_name), ("品级或器阶", value.grade_or_stage))
        .field(common["材料来源"], value.material_source)
        .field(
            common["灵石消耗"].split("{数量}")[0],
            M.text(value.spirit_stone_cost, tone="warning"),
        )
        .field(
            common["宗门灵石"],
            M.text(value.spirit_stones_after, tone="cultivation"),
        )
        .small(
            common["个人去向"] if value.destination != "万珍殿" else common["宗门去向"]
        )
        .build()
    )


def error(copy: Mapping[str, Mapping[str, str]], message: str) -> DocumentMessage:
    return (
        M.document()
        .section(copy["错误"].get("标题", "宗门洞天"), icon="notice")
        .line(M.status("炼制失败", tone="danger"), " ", message)
        .build()
    )


__all__ = ["completed", "error", "page", "preview"]
