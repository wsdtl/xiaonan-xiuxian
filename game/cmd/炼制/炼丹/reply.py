"""炼丹命令回复构造。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from message import DocumentBuilder, DocumentMessage, M

from ...actions import CommandAction, message_actions
from ...presentation import error_document, sentence
from game.features.liandan import (
    AlchemyAction,
    AlchemyCopy,
    AlchemyMaterial,
    AlchemyOverview,
    AlchemyPreview,
    AlchemyRecipeList,
    AlchemyResult,
)


def text(copy: AlchemyCopy, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
    return copy.text[section][key].format_map(values or {})


def _facility(value: AlchemyOverview | AlchemyPreview) -> str:
    return value.facility.name if value.facility else "随身"


def _saving(value: AlchemyPreview) -> str:
    return value.facility.saving_label() if value.facility else "无"


def overview(
    copy: AlchemyCopy,
    value: AlchemyOverview,
    actions: tuple[AlchemyAction, ...],
) -> DocumentMessage:
    name = _facility(value)
    builder = (
        M.document()
        .section(name, icon="game.box")
        .field(text(copy, "总览", "设施"), name)
        .line(text(copy, "总览", "引言", {"设施": name}))
        .section(text(copy, "总览", "分类"), icon="game.bag")
    )
    for index, (category, count) in enumerate(value.category_counts, start=1):
        builder.item(index, f"{category} · {count}种丹药")
    return builder.actions(message_actions(actions)).build()


def recipe_list(
    copy: AlchemyCopy,
    value: AlchemyRecipeList,
    actions: tuple[AlchemyAction, ...],
) -> DocumentMessage:
    name = value.facility.name if value.facility else "随身"
    builder = (
        M.document()
        .section(name, icon="game.box")
        .field(text(copy, "列表", "设施"), name)
        .section(value.category, icon="game.bag")
    )
    for index, entry in enumerate(value.entries, start=1):
        state = text(copy, "列表", "可炼" if entry.can_refine else "缺材")
        builder.item(
            index,
            M.command(M.text(entry.recipe.medicine_name), f"查看 {entry.recipe.medicine_name}"),
            " · ",
            M.status(state, tone="positive" if entry.can_refine else "warning"),
        ).small(f"材料：{len(entry.recipe.materials)} 项")
    builder.small(
        text(copy, "列表", "页码", {"当前页": value.page, "总页数": value.page_count})
    )
    return builder.actions(message_actions(actions)).build()


def preview(
    copy: AlchemyCopy,
    value: AlchemyPreview,
    actions: tuple[AlchemyAction, ...],
) -> DocumentMessage:
    name = _facility(value)
    builder = (
        M.document()
        .section(name, icon="game.box")
        .field(text(copy, "预览", "设施"), name)
        .section(value.recipe.medicine_name, icon="game.bag")
        .row(
            (
                text(copy, "预览", "成丹"),
                f"{value.medicine_grade_name}{value.recipe.medicine_name}",
            ),
        )
        .field(text(copy, "预览", "灵石消耗"), f"{value.spirit_stone_cost} 黄品")
        .field(text(copy, "预览", "材料节省"), _saving(value))
    )
    if value.beast_material is not None:
        builder.section(text(copy, "预览", "药引"), icon="game.material")
        _material(builder, 1, value.beast_material)
    if value.herb_materials:
        builder.section(text(copy, "预览", "辅材"), icon="game.material")
        for index, material in enumerate(value.herb_materials, start=1):
            _material(builder, index, material)
    if value.missing_materials:
        builder.section(text(copy, "列表", "缺材"), icon="game.pin_doc")
        for index, missing in enumerate(value.missing_materials, start=1):
            builder.item(index, f"{missing.role} · {missing.requirement} × {missing.quantity}")
    builder.line(
        M.status(
            "材料齐备" if value.can_refine else "材料不足",
            tone="positive" if value.can_refine else "danger",
        )
    )
    return builder.actions(message_actions(actions)).build()


def completed(
    copy: AlchemyCopy,
    value: AlchemyResult,
    actions: tuple[AlchemyAction, ...],
) -> DocumentMessage:
    preview_value = value.preview
    name = _facility(preview_value)
    builder = (
        M.document()
        .inline_section("结果", M.status("完成", tone="positive"), icon="game.pill")
        .section(name, icon="game.box")
        .field(text(copy, "完成", "设施"), name)
        .line(text(copy, "完成", "过程", {"设施": name}))
        .section(text(copy, "完成", "所得"), icon="game.bag")
        .field(
            f"{preview_value.medicine_grade_name}{preview_value.recipe.medicine_name}",
            f"纳戒数量 {value.quantity_after}",
        )
    )
    if value.treasure_activation is not None:
        activation = value.treasure_activation
        builder.section("灵宝", icon="game.amulet").field(activation.name, activation.summary)
    return builder.actions(message_actions(actions)).build()


def error(
    copy: AlchemyCopy,
    message: str,
    actions: Sequence[CommandAction] = (),
    *,
    command: str,
) -> DocumentMessage:
    return error_document(
        text(copy, "错误", "标题"),
        "game.pin_doc",
        text(copy, "错误", command),
        sentence(message),
        tone="danger",
        actions=actions,
        hint=text(copy, "错误", "格式"),
    )


def _material(builder: DocumentBuilder, index: int, material: AlchemyMaterial) -> None:
    builder.item(
        index,
        M.command(M.text(f"{material.grade_name}{material.name}"), f"查看 {material.name}"),
        f" × {material.quantity} · {material.category} · {material.relation}",
    )


__all__ = ["completed", "error", "overview", "preview", "recipe_list", "text"]
