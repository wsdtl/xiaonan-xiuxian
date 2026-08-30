"""炼丹命令回复构造。"""

from __future__ import annotations

from game.features.liandan import (
    AlchemyAction,
    AlchemyCopy,
    AlchemyOverview,
    AlchemyPreview,
    AlchemyRecipeList,
    AlchemyResult,
)
from message import M

from ...actions import message_actions
from ...presentation import sentence


def text(copy: AlchemyCopy, section: str, key: str, **values: object) -> str:
    return copy.text[section][key].format_map(values)


def overview(
    copy: AlchemyCopy,
    value: AlchemyOverview,
    actions: tuple[AlchemyAction, ...],
):
    alchemist = value.alchemist
    builder = (
        M.document()
        .header(text(copy, "总览", "标题", 地点=value.location_name, 炉名=alchemist.furnace_name))
        .section(alchemist.title, icon="item")
        .field(text(copy, "总览", "丹师"), alchemist.name)
        .field(text(copy, "总览", "丹门"), alchemist.heritage)
        .line(text(copy, "总览", "引言", 丹师=alchemist.name))
        .line(alchemist.speech["总览"].format(主持=alchemist.name))
        .section(text(copy, "总览", "分类"), icon="inventory")
    )
    for index, (category, count) in enumerate(value.category_counts, start=1):
        builder.item(index, f"{category} · {count}张丹方")
    return builder.actions(message_actions(actions)).build()


def recipe_list(
    copy: AlchemyCopy,
    value: AlchemyRecipeList,
    actions: tuple[AlchemyAction, ...],
):
    builder = (
        M.document()
        .header(text(copy, "列表", "标题", 地点=value.location_name, 分类=value.category))
        .section(value.alchemist.title, icon="item")
        .field(text(copy, "列表", "丹师"), value.alchemist.name)
        .section(value.category, icon="inventory")
    )
    for index, entry in enumerate(value.entries, start=1):
        state = text(copy, "列表", "可炼" if entry.can_refine else "缺材")
        builder.item(index, f"{entry.recipe.medicine_name} · {state}").line(
            f"丹方：{entry.recipe.recipe_id} · 难度：{entry.recipe.difficulty} · 炉法：{entry.recipe.method}"
        )
    builder.line(text(copy, "列表", "页码", 当前页=value.page, 总页数=value.page_count))
    return builder.actions(message_actions(actions)).build()


def preview(
    copy: AlchemyCopy,
    value: AlchemyPreview,
    actions: tuple[AlchemyAction, ...],
):
    alchemist = value.alchemist
    builder = (
        M.document()
        .header(text(copy, "预览", "标题", 地点=value.location_name, 炉名=alchemist.furnace_name))
        .section(alchemist.title, icon="item")
        .field(text(copy, "预览", "丹师"), alchemist.name)
        .line(alchemist.speech["审材"].format(主持=alchemist.name))
        .section(value.recipe.medicine_name, icon="inventory")
        .row(
            (text(copy, "预览", "丹方"), value.recipe.recipe_id),
            (text(copy, "预览", "成丹"), f"{value.medicine_grade_name}{value.recipe.medicine_name}"),
        )
        .row(
            (text(copy, "预览", "难度"), value.recipe.difficulty),
            (text(copy, "预览", "炉法"), value.recipe.method),
        )
        .section(text(copy, "预览", "药引"), icon="material")
    )
    if value.beast_material is None:
        builder.line("无")
    else:
        _material(builder, 1, value.beast_material)
    builder.section(text(copy, "预览", "辅材"), icon="material")
    for index, material in enumerate(value.herb_materials, start=1):
        _material(builder, index, material)
    if value.missing_materials:
        builder.section(text(copy, "列表", "缺材"), icon="notice")
        for index, missing in enumerate(value.missing_materials, start=1):
            builder.item(index, f"{missing.role} · {missing.trait} × {missing.quantity}")
    builder.line(alchemist.speech["齐备" if value.can_refine else "不足"].format(主持=alchemist.name))
    return builder.actions(message_actions(actions)).build()


def completed(
    copy: AlchemyCopy,
    value: AlchemyResult,
    actions: tuple[AlchemyAction, ...],
):
    preview_value = value.preview
    alchemist = preview_value.alchemist
    builder = (
        M.document()
        .header(text(copy, "完成", "标题", 地点=preview_value.location_name))
        .section(alchemist.title, icon="item")
        .field(text(copy, "完成", "丹师"), alchemist.name)
        .line(text(copy, "完成", "过程", 丹师=alchemist.name))
        .section(text(copy, "完成", "所得"), icon="inventory")
        .field(
            f"{preview_value.medicine_grade_name}{preview_value.recipe.medicine_name}",
            f"纳戒数量 {value.quantity_after}",
        )
        .line(alchemist.speech["完成"].format(主持=alchemist.name))
    )
    if value.treasure_activation is not None:
        activation = value.treasure_activation
        builder.section("先天灵宝", icon="item").field(
            activation.name, activation.summary
        )
    return builder.actions(message_actions(actions)).build()


def error(copy: AlchemyCopy, message: str):
    return M.document().section(text(copy, "错误", "标题"), icon="notice").line(sentence(message)).build()


def _material(builder, index: int, material) -> None:
    builder.item(
        index,
        f"{material.grade_name}{material.name} × {material.quantity} · {material.trait} · {material.relation}",
    )


__all__ = ["completed", "error", "overview", "preview", "recipe_list", "text"]
