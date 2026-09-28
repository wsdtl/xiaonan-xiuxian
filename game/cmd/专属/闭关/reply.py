"""闭关命令回复构造。"""

from __future__ import annotations

from message import DocumentBuilder, DocumentMessage, M

from collections.abc import Mapping

from game.features.biguan import (
    RetreatAction,
    RetreatCopy,
    RetreatFeature,
    RetreatProgress,
    RetreatSettlement,
    RetreatStarted,
    RetreatUserSummary,
)

from ...actions import message_actions
from ...presentation import duration, natural_deadline


def text(copy: RetreatCopy, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
    return copy.text[section][key].format_map(values or {})


def error(copy: RetreatCopy, message: str) -> DocumentMessage:
    return (
        M.document()
        .section(text(copy, "错误", "标题"), icon="notice")
        .line(M.status("闭关失败", tone="danger"), " ", message)
        .build()
    )


def started(
    copy: RetreatCopy,
    value: RetreatStarted,
    actions: tuple[RetreatAction, ...],
) -> DocumentMessage:
    return (
        M.document()
        .header(text(copy, "开始", "标题"))
        .inline_section("闭关状态", M.status("进行中", tone="positive"), icon="status")
        .section(value.location_name, icon="player")
        .row(
            (text(copy, "开始", "同行用户"), value.participant_count),
            (text(copy, "开始", "正式角色"), value.formal_character_count),
        )
        .row(
            (text(copy, "开始", "轮次"), value.maximum_rounds),
            (text(copy, "开始", "最晚出关"), natural_deadline(value.maximum_ends_at)),
        )
        .small(text(copy, "开始", "说明"))
        .actions(message_actions(actions))
        .build()
    )


def progress(
    copy: RetreatCopy,
    feature: RetreatFeature,
    value: RetreatProgress,
    actions: tuple[RetreatAction, ...],
) -> DocumentMessage:
    if value.completed_rounds >= value.maximum_rounds:
        progress_tail = (
            "状态",
            "已出关" if value.settled else "可以出关",
        )
    else:
        progress_tail = (
            text(copy, "进度", "剩余时间"),
            duration(value.remaining_seconds),
        )
    builder = (
        M.document()
        .header(text(copy, "进度", "标题"))
        .section(value.location_name, icon="status")
        .row(
            (
                text(copy, "进度", "轮次"),
                M.progress(
                    value.completed_rounds,
                    value.maximum_rounds,
                    tone="cultivation",
                    display="value",
                ),
            ),
            progress_tail,
        )
        .row(
            (text(copy, "进度", "同行用户"), value.participant_count),
            (text(copy, "进度", "累计感悟"), value.group_insight_count),
        )
        .section(text(copy, "进度", "本人感悟"), icon="skill")
    )
    if value.own_insights:
        for index, insight in enumerate(value.own_insights, start=1):
            builder.item(
                index,
                f"第{insight.round_number}轮 · "
                f"{feature.cultivation_label(insight.content_id, insight.grade_id)}",
            )
    else:
        builder.line(
            M.status("暂无", tone="muted"), " ", text(copy, "进度", "没有感悟")
        )
    if value.settled:
        note = ""
    elif value.can_end:
        note = text(copy, "进度", "可以出关")
    else:
        note = text(copy, "进度", "等待领队")
    if note:
        builder.line(
            M.status(
                "可出关" if value.can_end else "等待中",
                tone="positive" if value.can_end else "warning",
            ),
            " ",
            note,
        )
    return builder.actions(message_actions(actions)).build()


def settlement_page(
    copy: RetreatCopy,
    feature: RetreatFeature,
    value: RetreatSettlement,
    page: int,
    actions: tuple[RetreatAction, ...],
) -> DocumentMessage:
    total_pages = 1 + len(value.users)
    if page == 1:
        insight_count = sum(len(user.insights) for user in value.users)
        builder = (
            M.document()
            .header(text(copy, "总结", "标题"))
            .inline_section(
                "闭关状态", M.status("已出关", tone="positive"), icon="success"
            )
            .section(value.location_name, icon="status")
            .row(
                (
                    text(copy, "总结", "轮次"),
                    M.progress(
                        value.completed_rounds,
                        value.maximum_rounds,
                        tone="cultivation",
                        display="value",
                    ),
                ),
                (text(copy, "总结", "同行用户"), value.participant_count),
            )
            .field(text(copy, "总结", "感悟次数"), insight_count)
            .small(text(copy, "总结", "用户页", {"当前页": page, "总页数": total_pages}))
        )
    else:
        builder = _user_page(copy, feature, value.users[page - 2], page, total_pages)
    return builder.actions(message_actions(actions)).build()


def _user_page(
    copy: RetreatCopy,
    feature: RetreatFeature,
    value: RetreatUserSummary,
    page: int,
    total_pages: int,
) -> DocumentBuilder:
    builder = M.document().header(text(copy, "用户", "标题", {"人物": value.character_name}))
    if value.treasure_activation is not None:
        activation = value.treasure_activation
        builder.section("先天灵宝", icon="item").field(
            activation.name, activation.summary
        )
    for character in value.characters:
        title = text(copy, "用户", "道侣" if character.companion else "人物")
        level = (
            str(character.level_after)
            if character.level_before == character.level_after
            else f"{character.level_before} → {character.level_after}"
        )
        builder.section(f"{title} · {character.name}", icon="player").row(
            (
                text(copy, "用户", "经验"),
                M.text(f"+{character.experience_gained}", tone="positive"),
            ),
            (
                text(copy, "用户", "等级"),
                level,
            ),
        ).row(
            (
                text(copy, "用户", "血气"),
                M.text(_resource(character.health), tone="health"),
            ),
            (
                text(copy, "用户", "精神"),
                M.text(_resource(character.spirit), tone="spirit"),
            ),
        )
        if character.injury_changes:
            builder.field(
                text(copy, "用户", "疗伤"),
                "、".join(
                    f"{name} {before}→{after}"
                    for name, before, after in character.injury_changes
                ),
            )
        if character.injuries:
            builder.field(
                text(copy, "用户", "剩余伤势"),
                "、".join(f"{name}×{stacks}" for name, stacks in character.injuries),
            )
    builder.section(text(copy, "用户", "功法"), icon="skill")
    if value.insights:
        for index, insight in enumerate(value.insights, start=1):
            result = text(copy, "用户", insight.outcome or "复悟")
            builder.item(
                index,
                f"第{insight.round_number}轮 · {result} · ",
                M.command(
                    M.text(
                        feature.cultivation_label(insight.content_id, insight.grade_id),
                        tone="mystic",
                    ),
                    f"查看 {insight.content_id}",
                ),
            )
    else:
        builder.line(M.status("无", tone="muted"), " ", text(copy, "用户", "无"))
    return builder.small(text(copy, "总结", "用户页", {"当前页": page, "总页数": total_pages}))


def _resource(value: float) -> str:
    return (
        str(int(value))
        if value.is_integer()
        else f"{value:.3f}".rstrip("0").rstrip(".")
    )


__all__ = ["error", "progress", "settlement_page", "started", "text"]
