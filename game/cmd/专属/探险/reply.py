"""普通探险命令回复构造。"""

from __future__ import annotations

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


def text(copy: ExplorationCopy, section: str, key: str, **values: object) -> str:
    return copy.text[section][key].format_map(values)


def error(copy: ExplorationCopy, message: str):
    return (
        M.document()
        .section(text(copy, "错误", "标题"), icon="notice")
        .line(message)
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
        .section(value.location_name, icon="navigation")
        .row(
            (text(copy, "开始", "同行用户"), value.participant_count),
            (text(copy, "开始", "正式单位"), value.formal_unit_count),
        )
        .row(
            (text(copy, "开始", "预计场数"), value.battle_count),
            (text(copy, "开始", "结束时间"), natural_deadline(value.ends_at)),
        )
        .line(text(copy, "开始", "说明"))
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
                f"{value.unlocked_battles}/{value.total_battles}场",
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
            (text(copy, "进度", "累计灵石"), value.spirit_stones),
            (text(copy, "进度", "累计物品"), value.item_quantity),
        )
        .line(
            text(
                copy,
                "进度",
                ("已经结束" if value.can_settle else "等待领队"),
            )
            if value.ended
            else text(copy, "进度", "尚未结束")
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
            .section(value.location_name, icon="status")
            .row(
                (text(copy, "总结", "战斗"), f"{value.battle_count}场"),
                (text(copy, "总结", "战败敌人"), value.defeated_enemies),
            )
            .field(
                text(copy, "总结", "结局"),
                text(copy, "总结", "完成" if survived else "战败"),
            )
            .row(
                (text(copy, "总结", "同行用户"), value.participant_count),
                (text(copy, "总结", "总灵石"), value.total_spirit_stones),
            )
            .field(text(copy, "总结", "总物品"), value.total_item_quantity)
        )
        if not survived:
            builder.line(text(copy, "总结", "战败处理"))
        builder.line(text(copy, "总结", "用户页", 当前页=page, 总页数=total_pages))
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
    builder = M.document().header(text(copy, "用户", "标题", 人物=value.character_name))
    if value.treasure_activation is not None:
        activation = value.treasure_activation
        builder.section("先天灵宝", icon="item").field(
            activation.name, activation.summary
        )
    for character in value.characters:
        title = text(copy, "用户", "道侣" if character.companion else "人物")
        builder.section(f"{title} · {character.name}", icon="player").row(
            (text(copy, "用户", "最终血气"), _resource(character.health)),
            (text(copy, "用户", "最终精神"), _resource(character.spirit)),
        ).field(
            text(copy, "用户", "武器经验"),
            f"+{character.weapon_experience}",
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
            builder.item(index, f"{feature.item_label(item_id, grade_id)} × {quantity}")
    else:
        builder.line(text(copy, "用户", "无"))
    builder.section(text(copy, "用户", "所得"), icon="item").field(
        text(copy, "用户", "灵石"), value.spirit_stones
    )
    if value.drops:
        for index, (item_id, grade_id, quantity) in enumerate(value.drops, start=1):
            builder.item(index, f"{feature.item_label(item_id, grade_id)} × {quantity}")
    else:
        builder.line(text(copy, "用户", "无"))
    return builder.line(text(copy, "总结", "用户页", 当前页=page, 总页数=total_pages))


def _resource(value: float) -> str:
    return (
        str(int(value))
        if value.is_integer()
        else f"{value:.3f}".rstrip("0").rstrip(".")
    )


__all__ = ["error", "progress", "settlement_page", "started", "text"]
