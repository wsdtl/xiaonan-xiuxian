"""闭关命令回复构造。"""

from __future__ import annotations

from collections.abc import Sequence
from ...actions import CommandAction

from ...presentation import error_document

from message import DocumentMessage, M

from collections.abc import Mapping

from game.features.biguan import (
    RetreatAction,
    RetreatCopy,
    RetreatFeature,
    RetreatProgress,
    RetreatSettlement,
    RetreatStarted,
)

from ...actions import message_actions
from ...presentation import duration, span


def text(copy: RetreatCopy, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
    return copy.text[section][key].format_map(values or {})


def error(
    copy: RetreatCopy, message: str, actions: Sequence[CommandAction] = ()
) -> DocumentMessage:
    # 形状统一走 error_document（game/cmd/presentation.py），行为与原来一致。
    return error_document(        text(copy, "错误", "标题"), "game.pin_doc", "闭关失败", message, tone="danger",
        actions=actions,
    )


def started(
    copy: RetreatCopy,
    value: RetreatStarted,
    actions: tuple[RetreatAction, ...],
) -> DocumentMessage:
    builder = (
        M.document()

        .inline_section("状态", M.status("进行中", tone="positive"), icon="game.seed")
        .section(value.location_name, icon="game.role")
        .row(
            (text(copy, "开始", "参与用户"), value.participant_count),
            # 人物与道侣分开数：正式角色数里含道侣，减掉才是人物。
            (
                text(copy, "开始", "共修人物"),
                value.formal_character_count - value.companion_count,
            ),
        )
        .row(
            (text(copy, "开始", "轮次"), value.maximum_rounds),
            (
                text(copy, "开始", "预计用时"),
                span(value.started_at, value.maximum_ends_at),
            ),
        )
    )
    if value.companion_count:
        builder.field(text(copy, "开始", "同行道侣"), value.companion_count)
    return (
        builder.small(text(copy, "开始", "说明"))
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

        .section(value.location_name, icon="game.seed")
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
            (text(copy, "进度", "参与用户"), value.participant_count),
            (text(copy, "进度", "累计感悟"), value.group_insight_count),
        )
        .section(text(copy, "进度", "本人感悟"), icon="game.manual")
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


def settlement_summary(
    copy: RetreatCopy,
    feature: RetreatFeature,
    value: RetreatSettlement,
) -> DocumentMessage:
    """出关总结：单屏紧凑，不按用户分页。"""

    insight_count = sum(len(user.insights) for user in value.users)
    builder = (
        M.document()
        .inline_section(
            text(copy, "总结", "标题"),
            M.status("已出关", tone="positive"),
            icon="game.success",
        )
        .section(value.location_name, icon="game.seed")
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
            (text(copy, "总结", "参与用户"), value.participant_count),
        )
        .field(text(copy, "总结", "感悟次数"), insight_count)
    )
    for user in value.users:
        if user.treasure_activation is not None:
            activation = user.treasure_activation
            builder.field("灵宝", f"{activation.name} · {activation.summary}")
        for character in user.characters:
            title = text(copy, "用户", "道侣" if character.companion else "人物")
            level = (
                str(character.level_after)
                if character.level_before == character.level_after
                else f"{character.level_before} → {character.level_after}"
            )
            builder.section(f"{title} · {character.name}", icon="game.role").row(
                (
                    text(copy, "用户", "等级"),
                    level,
                ),
                (
                    text(copy, "用户", "经验"),
                    M.text(f"+{character.experience_gained}", tone="positive"),
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
                    "、".join(
                        f"{name}×{stacks}"
                        for name, stacks in character.injuries
                    ),
                )
        if user.insights:
            entries = []
            for insight in user.insights:
                entries.append(
                    f"第{insight.round_number}轮 "
                    f"{text(copy, '用户', insight.outcome or '复悟')} "
                    f"{feature.cultivation_label(insight.content_id, insight.grade_id)}"
                )
            builder.field(text(copy, "用户", "功法"), "、".join(entries))
        else:
            builder.field(text(copy, "用户", "功法"), text(copy, "用户", "无"))
    return builder.build()


def _resource(value: float) -> str:
    return (
        str(int(value))
        if value.is_integer()
        else f"{value:.3f}".rstrip("0").rstrip(".")
    )


__all__ = ["error", "progress", "settlement_summary", "started", "text"]
