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
            common["周期"].format_map({"时长": duration(value.facility.period_seconds)}),
        )
    )
    if not value.started:
        builder.line(M.status("未开始", tone="muted"), " ", common["未开始"])
    else:
        builder.line(M.status("生产中", tone="positive"))
        builder.field(
            "可收取",
            M.text(
                common["待结算"].format_map({"轮数": value.pending_cycles}),
                tone="emphasis",
            ),
        )
        builder.field(
            "下一轮", common["剩余"].format_map({"时长": duration(value.next_cycle_seconds)})
        )
        if value.pending_cycles == 0:
            builder.small(common["无待结算"])
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
        .line(M.status("生产已开启", tone="positive"))
        .small(
            common["开启说明"].format_map({"时长": duration(value.view.facility.period_seconds)})
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
        .line(M.status("收取完成", tone="positive"))
        .field("收取轮次", common["结算轮数"].format_map({"轮数": value.settled_cycles}))
    )
    if value.spirit_stones:
        builder.field(
            "灵石",
            M.text(value.spirit_stones, tone="cultivation"),
        )
    for index, output in enumerate(value.outputs, start=1):
        builder.item(
            index,
            M.command(
                M.text(f"{output.grade_name}{output.name}", tone="emphasis"),
                f"查看 {output.content_id}",
            ),
            f" × {output.quantity}",
        )
    if not value.outputs and not value.spirit_stones:
        builder.line(M.status("无产出", tone="muted"), " ", common["没有产出"])
    builder.field("灵藏灵石", M.text(value.spirit_stones_after, tone="cultivation"))
    builder.small("每 30 分钟一轮，可连续收取；在宗门洞天内由宗主或长老开启")
    return builder.actions(message_actions(actions)).build()


def error(copy: Mapping[str, Mapping[str, str]], message: str):
    return (
        M.document()
        .section(copy["通用"]["错误"], icon="notice")
        .line(M.status("生产失败", tone="danger"), " ", sentence(message))
        .build()
    )


__all__ = ["collected", "error", "started", "viewed"]
