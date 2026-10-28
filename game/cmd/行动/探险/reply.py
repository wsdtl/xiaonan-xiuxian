"""普通探险命令回复构造。"""

from __future__ import annotations

from collections.abc import Sequence

from ...actions import CommandAction

from ...presentation import error_document

from message import DocumentMessage, M

from collections.abc import Mapping

from game.features.tanxian import (
    ExplorationAction,
    ExplorationCopy,
    ExplorationFeature,
    ExplorationProgress,
    ExplorationSettlement,
    ExplorationStarted,
)

from ...actions import message_actions
from ...presentation import duration, span


def text(copy: ExplorationCopy, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
    return copy.text[section][key].format_map(values or {})


def error(
    copy: ExplorationCopy, message: str, actions: Sequence[CommandAction] = ()
) -> DocumentMessage:
    # 形状统一走 error_document（game/cmd/presentation.py），行为与原来一致。
    return error_document(        text(copy, "错误", "标题"), "game.pin_doc", "探险失败", message, tone="danger",
        actions=actions,
    )


def started(
    copy: ExplorationCopy,
    value: ExplorationStarted,
    actions: tuple[ExplorationAction, ...],
) -> DocumentMessage:
    builder = (
        M.document()

        .inline_section("状态", M.status("进行中", tone="positive"), icon="game.seed")
        .section(value.location_name, icon="game.compass")
        .row(
            (text(copy, "开始", "参与用户"), value.participant_count),
            # 人物与道侣分开数：单位数里含道侣，减掉才是人物。
            (
                text(copy, "开始", "出战人物"),
                value.formal_unit_count - value.companion_count,
            ),
        )
    )
    if value.companion_count:
        builder.field(text(copy, "开始", "同行道侣"), value.companion_count)
    return (
        builder.row(
            (text(copy, "开始", "预计场数"), value.battle_count),
            (text(copy, "开始", "预计用时"), span(value.started_at, value.ends_at)),
        )
        .small(text(copy, "开始", "说明"))
        .actions(message_actions(actions))
        .build()
    )


def progress(
    copy: ExplorationCopy,
    value: ExplorationProgress,
    actions: tuple[ExplorationAction, ...],
) -> DocumentMessage:
    builder = (
        M.document()

        .section(value.location_name, icon="game.seed")
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


def early_page(copy: ExplorationCopy, value: ExplorationSettlement) -> DocumentMessage:
    """提前结束的卡：没跑满就停，战果与奖励一概不计（那些只在跑满时才揭晓）。"""

    builder = (
        M.document()

        .inline_section(
            text(copy, "总结", "提前"),
            M.status(text(copy, "总结", "无战果"), tone="warning"),
            icon="game.pin_doc",
        )
        .section(value.location_name, icon="game.seed")
        .line(
            text(
                copy,
                "总结",
                "提前说明",
                {"场数": value.battle_count, "总场数": value.total_battles},
            )
        )
        .small(text(copy, "总结", "再来一次"))
    )
    if value.battle_count:
        builder.field(
            text(copy, "总结", "战报"),
            text(copy, "总结", "战报提示"),
        )
    return builder.build()


def settlement_summary(
    copy: ExplorationCopy,
    feature: ExplorationFeature,
    value: ExplorationSettlement,
) -> DocumentMessage:
    """探险总结：单屏紧凑，不按用户分页。"""

    # 一场都没跑完：别报「战败」（明明没人打），单独给一张说明卡。
    if value.early and not value.battle_count:
        return early_page(copy, value)
    survived = any(
        character.alive for user in value.users for character in user.characters
    )
    builder = (
        M.document()
        .inline_section(
            text(copy, "总结", "标题"),
            M.status(
                text(copy, "总结", "提前")
                if value.early
                else ("完成" if survived else "战败"),
                tone=(
                    "warning"
                    if value.early
                    else ("positive" if survived else "danger")
                ),
            ),
            icon="game.pin_doc" if value.early else ("game.success" if survived else "game.pin_doc"),
        )
        .section(value.location_name, icon="game.seed")
        .row(
            (text(copy, "总结", "战斗"), f"{value.battle_count}场"),
            (text(copy, "总结", "战败敌人"), value.defeated_enemies),
        )
        .field(
            text(copy, "总结", "结局"),
            M.status(
                text(copy, "总结", "提前")
                if value.early
                else text(copy, "总结", "完成" if survived else "战败"),
                tone="warning" if value.early else ("positive" if survived else "danger"),
            ),
        )
        .row(
            (text(copy, "总结", "参与用户"), value.participant_count),
            (
                text(copy, "总结", "总灵石"),
                M.text(value.total_spirit_stones, tone="cultivation"),
            ),
        )
        .field(text(copy, "总结", "总物品"), value.total_item_quantity)
    )
    if value.battle_count:
        builder.field(
            text(copy, "总结", "战报"),
            text(copy, "总结", "战报提示"),
        )
    if value.early:
        builder.line(
            text(
                copy,
                "总结",
                "提前说明",
                {"场数": value.battle_count, "总场数": value.total_battles},
            )
        )
    if not survived:
        builder.line(text(copy, "总结", "战败处理"))
    for user in value.users:
        if user.treasure_activation is not None:
            activation = user.treasure_activation
            builder.field(
                "灵宝",
                M.command(
                    activation.name, f"查看 {activation.name}"
                )
                + M.text(f" · {activation.summary}"),
            )
        for character in user.characters:
            title = text(copy, "用户", "道侣" if character.companion else "人物")
            builder.section(f"{title} · {character.name}", icon="game.role").row(
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
                    "、".join(
                        f"{name}×{stacks}"
                        for name, stacks in character.injuries
                    ),
                )
        if user.consumed:
            builder.field(
                text(copy, "用户", "消耗"),
                "、".join(
                    f"{feature.item_label(item_id, grade_id)} × {quantity}"
                    for item_id, grade_id, quantity in user.consumed
                ),
            )
        if user.drops:
            builder.field(
                text(copy, "用户", "所得"),
                f"{text(copy, '用户', '灵石')} {user.spirit_stones}、"
                + "、".join(
                    f"{feature.item_label(item_id, grade_id)} × {quantity}"
                    for item_id, grade_id, quantity in user.drops
                ),
            )
        elif user.spirit_stones:
            builder.field(
                text(copy, "用户", "所得"),
                f"{text(copy, '用户', '灵石')} {user.spirit_stones}",
            )
    return builder.build()


def _resource(value: float) -> str:
    return (
        str(int(value))
        if value.is_integer()
        else f"{value:.3f}".rstrip("0").rstrip(".")
    )


__all__ = ["error", "progress", "settlement_summary", "started", "text"]
