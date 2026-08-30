"""宗门资源生产命令回复。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from game.features.zongmen_shengchan import SectProductionAction
from message import M

from ...actions import message_actions
from ...presentation import duration, sentence


def viewed(
    copy: Mapping[str, Mapping[str, str]],
    value: Any,
    actions: tuple[SectProductionAction, ...],
):
    common = copy["通用"]
    text = copy[value.facility.kind]
    builder = (
        M.document()
        .header(text["标题"])
        .section("生产状态", icon="location")
        .field(
            "周期",
            common["周期"].format(时长=duration(value.facility.period_seconds)),
        )
    )
    if not value.started:
        builder.line(common["未开始"])
    else:
        builder.field("可收取", common["待结算"].format(轮数=value.pending_cycles))
        builder.field(
            "下一轮", common["剩余"].format(时长=duration(value.next_cycle_seconds))
        )
        if value.pending_cycles == 0:
            builder.line(common["无待结算"])
    return builder.actions(message_actions(actions)).build()


def started(
    copy: Mapping[str, Mapping[str, str]],
    value: Any,
    actions: tuple[SectProductionAction, ...],
):
    common = copy["通用"]
    text = copy[value.view.facility.kind]
    return (
        M.document()
        .header(text["标题"])
        .section(text["开启"], icon="success")
        .line(
            common["开启说明"].format(时长=duration(value.view.facility.period_seconds))
        )
        .actions(message_actions(actions))
        .build()
    )


def collected(
    copy: Mapping[str, Mapping[str, str]],
    value: Any,
    actions: tuple[SectProductionAction, ...],
):
    common = copy["通用"]
    text = copy[value.view.facility.kind]
    builder = (
        M.document()
        .header(text["标题"])
        .section(text["收取"], icon="success")
        .field("收取轮次", common["结算轮数"].format(轮数=value.settled_cycles))
    )
    if value.spirit_stones:
        builder.line(common["灵石"].format(数量=value.spirit_stones))
    for output in value.outputs:
        builder.item(
            output.content_id,
            common["产出"].format(
                品级=output.grade_name,
                名称=output.name,
                数量=output.quantity,
            ),
        )
    if not value.outputs and not value.spirit_stones:
        builder.line(common["没有产出"])
    builder.field("灵藏灵石", value.spirit_stones_after)
    return builder.actions(message_actions(actions)).build()


def error(copy: Mapping[str, Mapping[str, str]], message: str):
    return (
        M.document()
        .section(copy["通用"]["错误"], icon="notice")
        .line(sentence(message))
        .build()
    )


__all__ = ["collected", "error", "started", "viewed"]
