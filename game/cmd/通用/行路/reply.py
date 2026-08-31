"""行路命令回复构造。"""

from __future__ import annotations

from game.features.xinglu import TravelResult
from message import M

from ...actions import CommandAction, message_actions


def missing_destination():
    return (
        M.document()
        .section("行路", icon="navigation")
        .line(M.status("缺少地点", tone="warning"), " 去 地点名，或：去 x y")
        .line(M.command("查看全境地图", "地图"))
        .build()
    )


def query_error(message: str):
    return (
        M.document()
        .section("行路", icon="navigation")
        .line(M.status("无法抵达", tone="danger"), " ", message)
        .build()
    )


def conflict():
    return (
        M.document()
        .section("行路", icon="notice")
        .line(M.status("位置变化", tone="warning"))
        .small("本次行路没有覆盖新的落脚处，请重新查看人物。")
        .build()
    )


def success(
    result: TravelResult,
    actions: tuple[CommandAction, ...],
):
    plan = result.plan
    destination = plan.destination
    reply = (
        M.document()
        .header("抵达 · ", _location_name(destination))
        .inline_section("行路结果", M.status("已抵达", tone="positive"), icon="success")
        .section(f"行路 · {plan.travel_method}", icon="navigation")
    )
    for line in plan.narrative:
        reply.line(line)
    reply.section("落脚处", icon="map")
    reply.field("地点", _location_name(destination))
    reply.row(("区域", destination.region), ("地形", destination.terrain))
    reply.row(
        ("坐标", f"{destination.xy[0]}, {destination.xy[1]}"),
        ("海拔", f"{destination.altitude}米"),
    )
    return reply.actions(message_actions(actions)).build()


def _location_name(location) -> str:
    if location.location_name:
        return location.location_name
    return f"{location.region}·{location.terrain}（{location.xy[0]}, {location.xy[1]}）"


__all__ = ["conflict", "missing_destination", "query_error", "success"]
