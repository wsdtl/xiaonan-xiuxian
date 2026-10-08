"""炼器命令回复构造。"""

from __future__ import annotations

from collections.abc import Sequence, Mapping
from game.features.lianqi import ForgingMaterial

from message import DocumentBuilder, DocumentMessage, M


from game.features.lianqi import (
    ForgingAction,
    ForgingCopy,
    ForgingLawList,
    ForgingOverview,
    ForgingPreview,
    ForgingResult,
)

from ...actions import message_actions
from ...presentation import sentence


def text(copy: ForgingCopy, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
    return copy.text[section][key].format_map(values or {})


def overview(
    copy: ForgingCopy,
    value: ForgingOverview,
    actions: tuple[ForgingAction, ...],
) -> DocumentMessage:
    artisan = value.artisan
    builder = (
        M.document()
        .header(
            text(
                copy,
                "总览",
                "标题", {"地点": value.location_name, "炉名": artisan.furnace_name},
            )
        )
        .section(artisan.title, icon="weapon")
        .field(text(copy, "总览", "工匠"), artisan.name)
        .field(text(copy, "总览", "流派"), artisan.school)
        .line(text(copy, "总览", "引言", {"工匠": artisan.name}))
        .small(value.artisan.speech["总览"].format_map({"主持": value.artisan.name}))
        .section(text(copy, "总览", "器阶"), icon="item")
    )
    for index, (stage, count) in enumerate(value.stage_counts, start=1):
        builder.item(index, f"{stage} · {count}道器律")
    return builder.actions(message_actions(actions)).build()


def law_list(copy: ForgingCopy, value: ForgingLawList) -> DocumentMessage:
    builder = (
        M.document()
        .header(text(copy, "列表", "标题", {"地点": value.location_name, "器阶": value.stage}))
        .section(value.artisan.title, icon="weapon")
        .field(text(copy, "列表", "工匠"), value.artisan.name)
        .section(value.stage, icon="item")
    )
    for index, entry in enumerate(value.entries, start=1):
        state = text(copy, "列表", "可炼" if entry.can_forge else "缺材")
        builder.item(
            index,
            M.command(
                M.text(entry.law.name),
                f"查看 {entry.law.law_id}",
            ),
            " · ",
            M.status(state, tone="positive" if entry.can_forge else "warning"),
        ).small(f"编号：{entry.law.law_id} · 铸法：{entry.law.method}")
    builder.small(text(copy, "列表", "页码", {"当前页": 1, "总页数": 1}))
    return builder.build()


def preview(
    copy: ForgingCopy,
    value: ForgingPreview,
    actions: tuple[ForgingAction, ...],
) -> DocumentMessage:
    artisan = value.artisan
    builder = (
        M.document()
        .header(
            text(
                copy,
                "预览",
                "标题", {"地点": value.location_name, "炉名": artisan.furnace_name},
            )
        )
        .section(artisan.title, icon="weapon")
        .field(text(copy, "预览", "工匠"), artisan.name)
        .small(artisan.speech["审材"].format_map({"主持": artisan.name}))
        .section(value.law.name, icon="item")
        .row(
            (text(copy, "预览", "器律"), value.law.law_id),
            (text(copy, "预览", "器阶"), value.law.stage),
        )
        .field(text(copy, "预览", "铸法"), value.law.method)
    )
    # 没有材料就整个栏目都不开：空栏目与只印一个「无」一样，白占玩家的地方。
    if value.beast_materials:
        builder.section(text(copy, "预览", "兽引"), icon="material")
        _materials(builder, value.beast_materials, show_relation=False)
    if value.mineral_materials:
        builder.section(text(copy, "预览", "矿材"), icon="item")
        _materials(builder, value.mineral_materials, show_relation=True)
    if value.missing_materials:
        builder.section(text(copy, "列表", "缺材"), icon="notice")
        for index, missing in enumerate(value.missing_materials, start=1):
            builder.item(
                index, f"{missing.category} · {missing.trait} × {missing.quantity}"
            )
    builder.line(
        M.status(
            "材料齐备" if value.can_forge else "材料不足",
            tone="positive" if value.can_forge else "danger",
        )
    ).small(
        artisan.speech["齐备" if value.can_forge else "不足"].format_map({"主持": artisan.name})
    )
    return builder.actions(message_actions(actions)).build()


def completed(
    copy: ForgingCopy,
    value: ForgingResult,
    actions: tuple[ForgingAction, ...],
) -> DocumentMessage:
    preview_value = value.preview
    artisan = preview_value.artisan
    builder = (
        M.document()
        .header(text(copy, "完成", "标题", {"地点": preview_value.location_name}))
        .inline_section("炼器结果", M.status("完成", tone="positive"), icon="success")
        .section(artisan.title, icon="weapon")
        .field(text(copy, "完成", "工匠"), artisan.name)
        .line(text(copy, "完成", "过程", {"工匠": artisan.name}))
        .section(text(copy, "完成", "所得"), icon="item")
        .field(preview_value.law.name, f"器藏数量 {value.quantity_after}")
        .small(artisan.speech["完成"].format_map({"主持": artisan.name}))
    )
    if value.treasure_activation is not None:
        activation = value.treasure_activation
        builder.section("先天灵宝", icon="item").field(
            activation.name, activation.summary
        )
    return builder.actions(message_actions(actions)).build()


def error(copy: ForgingCopy, message: str) -> DocumentMessage:
    return (
        M.document()
        .section(text(copy, "错误", "标题"), icon="notice")
        .line(M.status("炼器失败", tone="danger"), " ", sentence(message))
        .build()
    )


def _materials(builder: DocumentBuilder, materials: Sequence[ForgingMaterial], *, show_relation: bool) -> None:
    if not materials:
        builder.line(M.status("无", tone="muted"))
        return
    for index, material in enumerate(materials, start=1):
        relation = f" · {material.relation}" if show_relation else ""
        builder.item(
            index,
            M.command(
                M.text(f"{material.grade_name}{material.name}"),
                f"查看 {material.item_id}",
            ),
            f" × {material.quantity} · {material.trait}{relation}",
        )


__all__ = ["completed", "error", "law_list", "overview", "preview", "text"]
