"""炼阵命令回复构造。"""

from __future__ import annotations

from collections.abc import Sequence
from ...actions import CommandAction

from ...presentation import candidate_lines, error_document

from game.features.lianzhen import FormationOverview, FormationPreview, FormationResult

from message import DocumentMessage, M

from collections.abc import Mapping

from game.features.lianzhen import FormationAction, FormationChoiceError, FormationCopy

from ...actions import message_actions
from ...presentation import sentence


def text(copy: FormationCopy, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
    return copy.text[section][key].format_map(values or {})


def overview(copy: FormationCopy, value: FormationOverview, actions: tuple[FormationAction, ...]) -> DocumentMessage:
    master = value.master
    builder = (
        M.document()

        .section(master.title, icon="combat")
        .field(text(copy, "总览", "阵师"), master.name)
        .line(text(copy, "总览", "引言", {"阵师": master.name}))
        .small(master.speech["总览"].format_map({"主持": master.name}))
        .section(text(copy, "总览", "阵法"), icon="item")
    )
    for index, entry in enumerate(value.entries, start=1):
        builder.item(
            index,
            M.command(
                M.text(entry.formation.name),
                f"查看 {entry.formation.name}",
            ),
        ).small(f"{entry.formation.core}")
    # 只有一页就不报页码，免得占一行什么都不说。
    if value.page_count > 1:
        builder.small(
            text(copy, "列表", "页码", {"当前页": value.page, "总页数": value.page_count})
        )
    return builder.actions(message_actions(actions)).build()


def preview(copy: FormationCopy, value: FormationPreview, actions: tuple[FormationAction, ...]) -> DocumentMessage:
    master = value.master
    builder = (
        M.document()

        .section(master.title, icon="combat")
        .field(text(copy, "预览", "阵师"), master.name)
        .small(master.speech["审材"].format_map({"主持": master.name}))
        .section(value.formation.name, icon="item")
        .row(
            (text(copy, "预览", "品级"), value.grade_name),
        )
        .row(
            (text(copy, "预览", "阵基"), f"承载 {value.capacity:g}"),
            (text(copy, "预览", "阵眼"), f"冲击 {value.impact:g}"),
        )
        .field(
            text(copy, "预览", "节点"), f"{value.nodes}位 · 传导 {value.transmission:g}"
        )
    )
    # 没有材料项就整个栏目都不开：空栏目白占玩家的地方。
    if value.requirements:
        builder.section(text(copy, "预览", "材料"), icon="material")
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
    ).small(
        master.speech["齐备" if value.can_form else "不足"].format_map({"主持": master.name})
    )
    return builder.actions(message_actions(actions)).build()


def completed(copy: FormationCopy, value: FormationResult, actions: tuple[FormationAction, ...]) -> DocumentMessage:
    preview_value = value.preview
    master = preview_value.master
    builder = (
        M.document()

        .inline_section("结果", M.status("完成", tone="positive"), icon="success")
        .section(master.title, icon="combat")
        .field(text(copy, "完成", "阵师"), master.name)
        .line(text(copy, "完成", "过程", {"阵师": master.name}))
        .section(text(copy, "完成", "所得"), icon="item")
        .field(
            f"{preview_value.grade_name}{preview_value.formation.name}",
            f"阵藏条目 {value.reserve_key} · 数量 {value.quantity_after}",
        )
        .small(master.speech["完成"].format_map({"主持": master.name}))
    )
    if value.treasure_activation is not None:
        activation = value.treasure_activation
        builder.section("灵宝", icon="item").field(
            activation.name, activation.summary
        )
    return builder.actions(message_actions(actions)).build()


def choose(
    copy: FormationCopy, exc: FormationChoiceError, *, command: str = "炼阵"
) -> DocumentMessage:
    """阵藏里有多条同名阵法：铺成选择卡，候选可点，点一下精确选中。

    与「布阵」同一形态：显示名带投入、命令用正规写法（**品级在前连写**的阵法名 + 三个投入数），
    点下去就是合法输入，玩家不必手打扩展位。
    """

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
    copy: FormationCopy, message: str, actions: Sequence[CommandAction] = (),
    *,
    command: str,
) -> DocumentMessage:
    # 形状统一走 error_document（game/cmd/presentation.py），行为与原来一致。
    return error_document(        text(copy, "错误", "标题"), "notice", text(copy, "错误", command), sentence(message), tone="danger",
        actions=actions,
    )


__all__ = ["choose", "completed", "error", "overview", "preview", "text"]
