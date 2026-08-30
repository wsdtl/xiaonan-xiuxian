"""采药命令回复构造。"""

from __future__ import annotations

from game.features.caiyao import (
    GatheringProgress,
    GatheringSettlement,
    GatheringStarted,
    GatheringUserSummary,
    HerbGatheringAction,
    HerbGatheringCopy,
    HerbGatheringFeature,
)
from message import M

from ...actions import message_actions
from ...presentation import duration, natural_deadline


def text(
    copy: HerbGatheringCopy, section: str, key: str, **values: object
) -> str:
    return copy.text[section][key].format_map(values)


def error(copy: HerbGatheringCopy, message: str):
    return M.document().section(text(copy, "错误", "标题"), icon="notice").line(message).build()


def started(
    copy: HerbGatheringCopy,
    value: GatheringStarted,
    actions: tuple[HerbGatheringAction, ...],
):
    return (
        M.document()
        .header(text(copy, "开始", "标题"))
        .section(value.place_name, icon="item")
        .field(text(copy, "开始", "地形"), value.terrain)
        .row(
            (text(copy, "开始", "同行用户"), value.participant_count),
            (text(copy, "开始", "采集单位"), value.gathering_unit_count),
        )
        .row(
            (text(copy, "开始", "轮次"), value.maximum_rounds),
            (text(copy, "开始", "最晚结束"), natural_deadline(value.maximum_ends_at)),
        )
        .line(text(copy, "开始", "说明"))
        .actions(message_actions(actions))
        .build()
    )


def progress(
    copy: HerbGatheringCopy,
    feature: HerbGatheringFeature,
    value: GatheringProgress,
    actions: tuple[HerbGatheringAction, ...],
):
    builder = (
        M.document()
        .header(text(copy, "进度", "标题"))
        .section(value.place_name, icon="status")
        .field(text(copy, "进度", "地形"), value.terrain)
        .row(
            (
                text(copy, "进度", "轮次"),
                f"{value.completed_rounds}/{value.maximum_rounds}轮",
            ),
            (text(copy, "进度", "剩余时间"), duration(value.remaining_seconds)),
        )
        .row(
            (text(copy, "进度", "同行用户"), value.participant_count),
            (text(copy, "进度", "累计数量"), value.group_quantity),
        )
        .section(text(copy, "进度", "本人所得"), icon="item")
    )
    if value.own_items:
        for index, item in enumerate(value.own_items, start=1):
            builder.item(
                index,
                f"{feature.item_label(item.item_id, item.grade_id)} × {item.quantity}",
            )
    else:
        builder.line(text(copy, "进度", "没有所得"))
    if value.settled:
        note = text(copy, "进度", "已经结束")
    elif value.can_end:
        note = text(copy, "进度", "可以结束")
    else:
        note = text(copy, "进度", "等待领队")
    return builder.line(note).actions(message_actions(actions)).build()


def settlement_page(
    copy: HerbGatheringCopy,
    feature: HerbGatheringFeature,
    value: GatheringSettlement,
    page: int,
    actions: tuple[HerbGatheringAction, ...],
):
    total_pages = 1 + len(value.users)
    if page == 1:
        builder = (
            M.document()
            .header(text(copy, "总结", "标题"))
            .section(value.place_name, icon="status")
            .field(text(copy, "总结", "地形"), value.terrain)
            .row(
                (
                    text(copy, "总结", "轮次"),
                    f"{value.completed_rounds}/{value.maximum_rounds}轮",
                ),
                (text(copy, "总结", "同行用户"), value.participant_count),
            )
            .field(text(copy, "总结", "灵植总数"), value.total_quantity)
            .line(text(copy, "总结", "用户页", 当前页=page, 总页数=total_pages))
        )
    else:
        builder = _user_page(copy, feature, value.users[page - 2], page, total_pages)
    return builder.actions(message_actions(actions)).build()


def _user_page(
    copy: HerbGatheringCopy,
    feature: HerbGatheringFeature,
    value: GatheringUserSummary,
    page: int,
    total_pages: int,
):
    builder = M.document().header(text(copy, "用户", "标题", 人物=value.character_name))
    if value.treasure_activation is not None:
        activation = value.treasure_activation
        builder.section("先天灵宝", icon="item").field(
            activation.name, activation.summary
        )
    builder.section(text(copy, "用户", "道侣相助"), icon="player").line(
        value.assisting_companion_name or text(copy, "用户", "没有道侣")
    )
    builder.section(text(copy, "用户", "灵植"), icon="item")
    if value.items:
        for index, item in enumerate(value.items, start=1):
            builder.item(
                index,
                f"{feature.item_label(item.item_id, item.grade_id)} × {item.quantity}",
            )
    else:
        builder.line(text(copy, "用户", "无"))
    return builder.line(text(copy, "总结", "用户页", 当前页=page, 总页数=total_pages))


__all__ = ["error", "progress", "settlement_page", "started", "text"]
