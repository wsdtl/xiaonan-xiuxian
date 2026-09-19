"""普通探险命令回复构造。"""

from __future__ import annotations

from collections.abc import Mapping

from game.features.tanxian import (
    ExplorationAction,
    ExplorationCopy,
    ExplorationFeature,
    ExplorationProgress,
    ExplorationSettlement,
    ExplorationStarted,
    ExplorationUserSummary,
)
from message import M

from ...actions import message_actions
from ...presentation import duration, natural_deadline


def text(copy: ExplorationCopy, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
    return copy.text[section][key].format_map(values or {})


def error(copy: ExplorationCopy, message: str):
    return (
        M.document()
        .section(text(copy, "错误", "标题"), icon="notice")
        .line(M.status("探险失败", tone="danger"), " ", message)
        .build()
    )


def started(
    copy: ExplorationCopy,
    value: ExplorationStarted,
    actions: tuple[ExplorationAction, ...],
):
    return (
        M.document()
        .header(text(copy, "开始", "标题"))
        .inline_section("探险状态", M.status("进行中", tone="positive"), icon="status")
        .section(value.location_name, icon="navigation")
        .row(
            (text(copy, "开始", "同行用户"), value.participant_count),
            (text(copy, "开始", "正式单位"), value.formal_unit_count),
        )
        .row(
            (text(copy, "开始", "预计场数"), value.battle_count),
            (text(copy, "开始", "结束时间"), natural_deadline(value.ends_at)),
        )
        .small(text(copy, "开始", "说明"))
        .actions(message_actions(actions))
        .build()
    )


def progress(
    copy: ExplorationCopy,
    value: ExplorationProgress,
    actions: tuple[ExplorationAction, ...],
):
    builder = (
        M.document()
        .header(text(copy, "进度", "标题"))
        .section(value.location_name, icon="status")
        .row(
            (
                text(copy, "进度", "进度"),
                M.progress(
                    value.unlocked_battles,
                    value.total_battles,
                    tone="cultivation",
                    display="value",
                ),
            ),
            (
                text(copy, "进度", "剩余时间"),
                duration(value.remaining_seconds),
            ),
        )
        .row(
            (text(copy, "进度", "我方存活"), value.surviving_allies),
            (text(copy, "进度", "战败敌人"), value.defeated_enemies),
        )
        .row(
            (
                text(copy, "进度", "累计灵石"),
                M.text(value.spirit_stones, tone="cultivation"),
            ),
            (text(copy, "进度", "累计物品"), value.item_quantity),
        )
        .line(
            M.status(
                "可结算" if value.can_settle else "等待中",
                tone="positive" if value.can_settle else "warning",
            ),
            " ",
            text(
                copy,
                "进度",
                ("已经结束" if value.can_settle else "等待领队"),
            )
            if value.ended
            else text(copy, "进度", "尚未结束"),
        )
    )
    return builder.actions(message_actions(actions)).build()


def settlement_page(
    copy: ExplorationCopy,
    feature: ExplorationFeature,
    value: ExplorationSettlement,
    page: int,
    actions: tuple[ExplorationAction, ...],
):
    total_pages = 1 + len(value.users)
    if page == 1:
        survived = any(
            character.alive for user in value.users for character in user.characters
        )
        builder = (
            M.document()
            .header(text(copy, "总结", "标题"))
            .inline_section(
                "探险结局",
                M.status(
                    "完成" if survived else "战败",
                    tone="positive" if survived else "danger",
                ),
                icon="success" if survived else "notice",
            )
            .section(value.location_name, icon="status")
            .row(
                (text(copy, "总结", "战斗"), f"{value.battle_count}场"),
                (text(copy, "总结", "战败敌人"), value.defeated_enemies),
            )
            .field(
                text(copy, "总结", "结局"),
                M.status(
                    text(copy, "总结", "完成" if survived else "战败"),
                    tone="positive" if survived else "danger",
                ),
            )
            .row(
                (text(copy, "总结", "同行用户"), value.participant_count),
                (
                    text(copy, "总结", "总灵石"),
                    M.text(value.total_spirit_stones, tone="cultivation"),
                ),
            )
            .field(text(copy, "总结", "总物品"), value.total_item_quantity)
        )
        if not survived:
            builder.line(text(copy, "总结", "战败处理"))
        builder.small(text(copy, "总结", "用户页", {"当前页": page, "总页数": total_pages}))
    else:
        builder = _user_page(copy, feature, value.users[page - 2], page, total_pages)
    return builder.actions(message_actions(actions)).build()


def _user_page(
    copy: ExplorationCopy,
    feature: ExplorationFeature,
    value: ExplorationUserSummary,
    page: int,
    total_pages: int,
):
    builder = M.document().header(text(copy, "用户", "标题", {"人物": value.character_name}))
    if value.treasure_activation is not None:
        activation = value.treasure_activation
        builder.section("先天灵宝", icon="item").field(
            activation.name, activation.summary
        )
    for character in value.characters:
        title = text(copy, "用户", "道侣" if character.companion else "人物")
        builder.section(f"{title} · {character.name}", icon="player").row(
            (
                "状态",
                M.status(
                    "存活" if character.alive else "身死",
                    tone="positive" if character.alive else "danger",
                ),
            ),
            (
                text(copy, "用户", "最终血气"),
                M.text(_resource(character.health), tone="health"),
            ),
        ).field(
            text(copy, "用户", "最终精神"),
            M.text(_resource(character.spirit), tone="spirit"),
        ).field(
            text(copy, "用户", "武器经验"),
            M.text(f"+{character.weapon_experience}", tone="positive"),
        )
        if character.injury_changes:
            builder.field(
                text(copy, "用户", "伤势变化"),
                "、".join(
                    f"{name} {before}→{after}"
                    for name, before, after in character.injury_changes
                ),
            )
        if character.injuries:
            builder.field(
                text(copy, "用户", "当前伤势"),
                "、".join(f"{name}×{stacks}" for name, stacks in character.injuries),
            )
    builder.section(text(copy, "用户", "消耗"), icon="item")
    if value.consumed:
        for index, (item_id, grade_id, quantity) in enumerate(value.consumed, start=1):
            builder.item(index, *_item_parts(feature, item_id, grade_id, quantity))
    else:
        builder.line(M.status("无", tone="muted"), " ", text(copy, "用户", "无"))
    builder.section(text(copy, "用户", "所得"), icon="item").field(
        text(copy, "用户", "灵石"), M.text(value.spirit_stones, tone="cultivation")
    )
    if value.drops:
        for index, (item_id, grade_id, quantity) in enumerate(value.drops, start=1):
            builder.item(index, *_item_parts(feature, item_id, grade_id, quantity))
    else:
        builder.line(M.status("无", tone="muted"), " ", text(copy, "用户", "无"))
    return builder.small(text(copy, "总结", "用户页", {"当前页": page, "总页数": total_pages}))


def _item_parts(
    feature: ExplorationFeature, item_id: str, grade_id: str, quantity: int
) -> tuple[object, ...]:
    return (
        M.command(
            M.text(feature.item_label(item_id, grade_id), tone="emphasis"),
            f"查看 {item_id}",
        ),
        f" × {quantity}",
    )


def _resource(value: float) -> str:
    return (
        str(int(value))
        if value.is_integer()
        else f"{value:.3f}".rstrip("0").rstrip(".")
    )


__all__ = ["error", "progress", "settlement_page", "started", "text"]
