"""炼器命令回复构造。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from message import DocumentBuilder, DocumentMessage, M

from ...actions import CommandAction, message_actions
from ...presentation import error_document, sentence
from game.features.lianqi import (
    ForgingAction,
    ForgingCopy,
    ForgingLawList,
    ForgingMaterial,
    ForgingOverview,
    ForgingPreview,
    ForgingResult,
)


def text(copy: ForgingCopy, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
    return copy.text[section][key].format_map(values or {})


def _facility(value: ForgingOverview | ForgingPreview) -> str:
    return value.facility.name if value.facility else "随身"


def _saving(value: ForgingPreview) -> str:
    return value.facility.saving_label() if value.facility else "无"


def overview(
    copy: ForgingCopy,
    value: ForgingOverview,
    actions: tuple[ForgingAction, ...],
) -> DocumentMessage:
    name = _facility(value)
    builder = (
        M.document()
        .section(name, icon="game.dagger")
        .field(text(copy, "总览", "设施"), name)
        .line(text(copy, "总览", "引言", {"设施": name}))
        .section(text(copy, "总览", "器阶"), icon="game.box")
    )
    for index, (stage, count) in enumerate(value.stage_counts, start=1):
        builder.item(index, f"{stage} · {count}道器律")
    return builder.actions(message_actions(actions)).build()


def law_list(copy: ForgingCopy, value: ForgingLawList) -> DocumentMessage:
    name = value.facility.name if value.facility else "随身"
    builder = (
        M.document()
        .section(name, icon="game.dagger")
        .field(text(copy, "列表", "设施"), name)
        .section(value.stage, icon="game.box")
    )
    for index, entry in enumerate(value.entries, start=1):
        state = text(copy, "列表", "可炼" if entry.can_forge else "缺材")
        builder.item(
            index,
            M.command(M.text(entry.law.name), f"查看 {entry.law.name}"),
            " · ",
            M.status(state, tone="positive" if entry.can_forge else "warning"),
        )
    builder.small(text(copy, "列表", "页码", {"当前页": 1, "总页数": 1}))
    return builder.build()


def preview(
    copy: ForgingCopy,
    value: ForgingPreview,
    actions: tuple[ForgingAction, ...],
) -> DocumentMessage:
    name = _facility(value)
    builder = (
        M.document()
        .section(name, icon="game.dagger")
        .field(text(copy, "预览", "设施"), name)
        .section(value.law.name, icon="game.box")
        .row((text(copy, "预览", "器阶"), value.law.stage))
        .field(text(copy, "预览", "灵石消耗"), f"{value.spirit_stone_cost} 黄品")
        .field(text(copy, "预览", "材料节省"), _saving(value))
    )
    if value.beast_materials:
        builder.section(text(copy, "预览", "兽宝"), icon="game.material")
        _materials(builder, value.beast_materials, show_relation=False)
    if value.mineral_materials:
        builder.section(text(copy, "预览", "矿材"), icon="game.box")
        _materials(builder, value.mineral_materials, show_relation=True)
    if value.missing_materials:
        builder.section(text(copy, "列表", "缺材"), icon="game.pin_doc")
        for index, missing in enumerate(value.missing_materials, start=1):
            builder.item(index, f"{missing.category} · {missing.trait} × {missing.quantity}")
    builder.line(
        M.status(
            "材料齐备" if value.can_forge else "材料不足",
            tone="positive" if value.can_forge else "danger",
        )
    )
    return builder.actions(message_actions(actions)).build()


def completed(
    copy: ForgingCopy,
    value: ForgingResult,
    actions: tuple[ForgingAction, ...],
) -> DocumentMessage:
    preview_value = value.preview
    name = _facility(preview_value)
    builder = (
        M.document()
        .inline_section("结果", M.status("完成", tone="positive"), icon="game.hammer")
        .section(name, icon="game.dagger")
        .field(text(copy, "完成", "设施"), name)
        .line(text(copy, "完成", "过程", {"设施": name}))
        .section(text(copy, "完成", "所得"), icon="game.box")
        .field(preview_value.law.name, f"器藏数量 {value.quantity_after}")
    )
    if value.treasure_activation is not None:
        activation = value.treasure_activation
        builder.section("灵宝", icon="game.amulet").field(activation.name, activation.summary)
    return builder.actions(message_actions(actions)).build()


def error(
    copy: ForgingCopy,
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


def _materials(builder: DocumentBuilder, materials: Sequence[ForgingMaterial], *, show_relation: bool) -> None:
    if not materials:
        builder.line(M.status("无", tone="muted"))
        return
    for index, material in enumerate(materials, start=1):
        relation = f" · {material.relation}" if show_relation else ""
        builder.item(
            index,
            M.command(M.text(f"{material.grade_name}{material.name}"), f"查看 {material.name}"),
            f" × {material.quantity} · {material.trait}{relation}",
        )


__all__ = ["completed", "error", "law_list", "overview", "preview", "text"]
