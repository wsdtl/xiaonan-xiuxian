"""采矿命令回复构造。"""

from __future__ import annotations

from game.features.caikuang import (
    GatheringProgress,
    GatheringSettlement,
    GatheringStarted,
    GatheringUserSummary,
    OreGatheringAction,
    OreGatheringCopy,
    OreGatheringFeature,
)
from message import M

from ...actions import message_actions
from ...presentation import duration, natural_deadline


def text(copy: OreGatheringCopy, section: str, key: str, **values: object) -> str:
    return copy.text[section][key].format_map(values)


def error(copy: OreGatheringCopy, message: str):
    return (
        M.document()
        .section(text(copy, "错误", "标题"), icon="notice")
        .line(M.status("采矿失败", tone="danger"), " ", message)
        .build()
    )


def started(
    copy: OreGatheringCopy,
    value: GatheringStarted,
    actions: tuple[OreGatheringAction, ...],
):
    return (
        M.document()
        .header(text(copy, "开始", "标题"))
        .inline_section("采集状态", M.status("进行中", tone="positive"), icon="status")
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
        .small(text(copy, "开始", "说明"))
        .actions(message_actions(actions))
        .build()
    )


def progress(
    copy: OreGatheringCopy,
    feature: OreGatheringFeature,
    value: GatheringProgress,
    actions: tuple[OreGatheringAction, ...],
):
    builder = (
        M.document()
        .header(text(copy, "进度", "标题"))
        .section(value.place_name, icon="status")
        .field(text(copy, "进度", "地形"), value.terrain)
        .row(
            (
                text(copy, "进度", "轮次"),
                M.progress(
                    value.completed_rounds,
                    value.maximum_rounds,
                    tone="metal",
                    display="value",
                ),
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
            builder.item(index, *_item_parts(feature, item))
    else:
        builder.line(
            M.status("暂无", tone="muted"), " ", text(copy, "进度", "没有所得")
        )
    if value.settled:
        note = text(copy, "进度", "已经结束")
    elif value.can_end:
        note = text(copy, "进度", "可以结束")
    else:
        note = text(copy, "进度", "等待领队")
    tone = "positive" if value.settled or value.can_end else "warning"
    return (
        builder.line(
            M.status(
                "已完成" if value.settled else "可结束" if value.can_end else "等待中",
                tone=tone,
            ),
            " ",
            note,
        )
        .actions(message_actions(actions))
        .build()
    )


def settlement_page(
    copy: OreGatheringCopy,
    feature: OreGatheringFeature,
    value: GatheringSettlement,
    page: int,
    actions: tuple[OreGatheringAction, ...],
):
    total_pages = 1 + len(value.users)
    if page == 1:
        builder = (
            M.document()
            .header(text(copy, "总结", "标题"))
            .inline_section(
                "采集状态", M.status("已完成", tone="positive"), icon="success"
            )
            .section(value.place_name, icon="status")
            .field(text(copy, "总结", "地形"), value.terrain)
            .row(
                (
                    text(copy, "总结", "轮次"),
                    M.progress(
                        value.completed_rounds,
                        value.maximum_rounds,
                        tone="metal",
                        display="value",
                    ),
                ),
                (text(copy, "总结", "同行用户"), value.participant_count),
            )
            .field(
                text(copy, "总结", "灵矿总数"),
                M.text(value.total_quantity, tone="metal"),
            )
            .small(text(copy, "总结", "用户页", 当前页=page, 总页数=total_pages))
        )
    else:
        builder = _user_page(copy, feature, value.users[page - 2], page, total_pages)
    return builder.actions(message_actions(actions)).build()


def _user_page(
    copy: OreGatheringCopy,
    feature: OreGatheringFeature,
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
    builder.section(text(copy, "用户", "道侣相助"), icon="player")
    if value.assisting_companion_name:
        builder.line(M.text(value.assisting_companion_name, tone="companion"))
    else:
        builder.line(M.status("无", tone="muted"), " ", text(copy, "用户", "没有道侣"))
    builder.section(text(copy, "用户", "灵矿"), icon="item")
    if value.items:
        for index, item in enumerate(value.items, start=1):
            builder.item(index, *_item_parts(feature, item))
    else:
        builder.line(M.status("无", tone="muted"), " ", text(copy, "用户", "无"))
    return builder.small(text(copy, "总结", "用户页", 当前页=page, 总页数=total_pages))


def _item_parts(feature: OreGatheringFeature, item) -> tuple[object, ...]:
    return (
        M.command(
            M.text(feature.item_label(item.item_id, item.grade_id), tone="metal"),
            f"查看 {item.item_id}",
        ),
        f" × {item.quantity}",
    )


__all__ = ["error", "progress", "settlement_page", "started", "text"]
