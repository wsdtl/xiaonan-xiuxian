"""炼阵命令回复构造。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from message import DocumentMessage, M

from ...actions import CommandAction, message_actions
from ...presentation import candidate_lines, error_document, sentence
from game.features.lianzhen import (
    FormationAction,
    FormationChoiceError,
    FormationCopy,
    FormationOverview,
    FormationPreview,
    FormationResult,
)


def text(copy: FormationCopy, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
    return copy.text[section][key].format_map(values or {})


def _facility(value: FormationOverview | FormationPreview) -> str:
    return value.facility.name if value.facility else "随身"


def _saving(value: FormationPreview) -> str:
    return value.facility.saving_label() if value.facility else "无"


def overview(copy: FormationCopy, value: FormationOverview, actions: tuple[FormationAction, ...]) -> DocumentMessage:
    name = _facility(value)
    builder = (
        M.document()
        .section(name, icon="game.swords")
        .field(text(copy, "总览", "设施"), name)
        .line(text(copy, "总览", "引言", {"设施": name}))
        .section(text(copy, "总览", "阵法"), icon="game.box")
    )
    for index, entry in enumerate(value.entries, start=1):
        builder.item(
            index,
            M.command(M.text(entry.formation.name), f"查看 {entry.formation.name}"),
        ).small(entry.formation.core)
    if value.page_count > 1:
        builder.small(
            text(copy, "列表", "页码", {"当前页": value.page, "总页数": value.page_count})
        )
    return builder.actions(message_actions(actions)).build()


def preview(copy: FormationCopy, value: FormationPreview, actions: tuple[FormationAction, ...]) -> DocumentMessage:
    name = _facility(value)
    builder = (
        M.document()
        .section(name, icon="game.swords")
        .field(text(copy, "预览", "设施"), name)
        .section(value.formation.name, icon="game.box")
        .row((text(copy, "预览", "品级"), value.grade_name))
        .row(
            (text(copy, "预览", "阵基"), f"承载 {value.capacity:g}"),
            (text(copy, "预览", "阵眼"), f"冲击 {value.impact:g}"),
        )
        .field(text(copy, "预览", "节点"), f"{value.nodes}位 · 传导 {value.transmission:g}")
        .field(text(copy, "预览", "灵石消耗"), f"{value.spirit_stone_cost} 黄品")
        .field(text(copy, "预览", "材料节省"), _saving(value))
    )
    if value.requirements:
        builder.section(text(copy, "预览", "材料"), icon="game.material")
    for index, requirement in enumerate(value.requirements, start=1):
        builder.item(
            index,
            requirement.category,
            " · ",
            M.progress(
                requirement.selected,
                requirement.required,
                tone="mystic" if not requirement.missing else "warning",
                display="value",
            ),
        )
        if requirement.missing:
            builder.small(f"尚缺 {requirement.missing}")
    builder.line(
        M.status(
            "材料齐备" if value.can_form else "材料不足",
            tone="positive" if value.can_form else "danger",
        )
    )
    return builder.actions(message_actions(actions)).build()


def completed(copy: FormationCopy, value: FormationResult, actions: tuple[FormationAction, ...]) -> DocumentMessage:
    preview_value = value.preview
    name = _facility(preview_value)
    builder = (
        M.document()
        .inline_section("结果", M.status("完成", tone="positive"), icon="game.blue_diamond")
        .section(name, icon="game.swords")
        .field(text(copy, "完成", "设施"), name)
        .line(text(copy, "完成", "过程", {"设施": name}))
        .section(text(copy, "完成", "所得"), icon="game.box")
        .field(
            f"{preview_value.grade_name}{preview_value.formation.name}",
            f"阵藏条目 {value.reserve_key} · 数量 {value.quantity_after}",
        )
    )
    if value.treasure_activation is not None:
        activation = value.treasure_activation
        builder.section("灵宝", icon="game.amulet").field(activation.name, activation.summary)
    return builder.actions(message_actions(actions)).build()


def choose_grade(copy: FormationCopy, identifier: str) -> DocumentMessage:
    """未写品级时只出品级候选，不执行、不查库存。"""

    builder = (
        M.document()
        .section(f"{identifier} · 选择品级", icon="game.blue_diamond")
        .line("补一个品级再炼；这一步只填命令，不消耗材料。")
    )
    for index, grade in enumerate(("黄品", "玄品", "地品", "天品", "圣品"), start=1):
        builder.item(index, M.command(grade, f"炼阵 {grade}{identifier}"))
    return builder.build()


def choose(copy: FormationCopy, exc: FormationChoiceError, *, command: str = "炼阵") -> DocumentMessage:
    builder = M.document()
    candidate_lines(
        builder,
        title=text(copy, "错误", "选择标题"),
        entries=tuple(
            (candidate.label, f"{command} {candidate.tail}", candidate.detail)
            for candidate in exc.candidates
        ),
        footer=text(copy, "错误", "选择尾注"),
    )
    return builder.build()


def error(
    copy: FormationCopy,
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
    )


__all__ = ["choose", "choose_grade", "completed", "error", "overview", "preview", "text"]
