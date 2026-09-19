"""位置命令回复构造。"""

from __future__ import annotations

from game.features.weizhi import (
    CurrentPositionView,
    NearbyCultivatorPage,
    NearbyOverview,
    NearbyWorldLocation,
    NearbyWorldLocations,
    PositionCopy,
)
from message import M

from ...actions import CommandAction, message_actions


def current(
    copy: PositionCopy,
    result: CurrentPositionView,
    actions: tuple[CommandAction, ...],
):
    location = result.location
    builder = (
        M.document()
        .header(result.space_name or _location_name(copy, location))
        .section(copy.current_place_section, icon=copy.location_icon)
    )
    if result.space_type == "地表":
        builder.row(
            (copy.region_label, location.region), (copy.terrain_label, location.terrain)
        ).row(
            (copy.coordinate_label, _coordinate(copy, location.xy)),
            (copy.altitude_label, copy.altitude.format_map({"海拔": location.altitude})),
        )
    else:
        builder.row(
            ("空间", result.space_type),
            ("山门", _location_name(copy, location)),
        )
    if result.local_cultivators:
        builder.inline_section(
            copy.local_cultivators_section,
            M.text(f"{len(result.local_cultivators)}人", tone="emphasis"),
            icon=copy.cultivator_icon,
        )
    if result.active_companion is not None:
        builder.inline_section(
            copy.active_companion_section,
            M.command(
                M.text(result.active_companion.name, tone="companion"),
                f"查看 {result.active_companion.companion_id}",
            ),
            icon=copy.cultivator_icon,
        )
    return builder.actions(message_actions(actions)).build()


def nearby_overview(
    copy: PositionCopy, result: NearbyOverview, actions: tuple[CommandAction, ...]
):
    location = result.current.location
    location_name = result.current.space_name or _location_name(copy, location)
    surface = result.current.space_type == "地表"
    builder = (
        M.document()
        .header(
            copy.overview_title.format_map({"地点": location_name}) if surface else location_name
        )
        .section(copy.overview_cultivators_section, icon=copy.cultivator_icon)
    )
    if surface:
        builder.row(
            (copy.overview_local_label, len(result.current.local_cultivators)),
            (copy.overview_visiting_label, result.visiting_cultivator_count),
        ).section(copy.overview_locations_section, icon=copy.location_icon)
    else:
        builder.field(copy.overview_nearby_label, result.visiting_cultivator_count)
        return builder.actions(message_actions(actions)).build()
    if result.locations:
        for index, nearby in enumerate(result.locations, start=1):
            _append_location(builder, copy, index, nearby)
    else:
        builder.line(copy.overview_no_locations)
    builder.section(copy.overview_current_section, icon=copy.navigation_icon)
    builder.field(copy.overview_current_label, location_name)
    builder.row(
        (copy.region_label, location.region), (copy.terrain_label, location.terrain)
    )
    return builder.actions(message_actions(actions)).build()


def nearby_cultivators(
    copy: PositionCopy,
    result: NearbyCultivatorPage,
    actions: tuple[CommandAction, ...],
):
    builder = M.document().header(copy.cultivators_title)
    if result.active_companion is not None:
        builder.section(
            copy.cultivators_active_section, icon=copy.cultivator_icon
        ).field(
            result.active_companion.name,
            copy.cultivator_summary.format_map(
                {"境界": result.active_companion.realm_name, "等级": result.active_companion.level, "性别": result.active_companion.gender, "状态": ""},
            ),
        )
    if result.local_cultivators:
        builder.section(copy.cultivators_local_section, icon=copy.cultivator_icon)
        for local in result.local_cultivators:
            builder.line(
                M.command(local.name, f"查看 {local.companion_id}"),
                " · ",
                copy.cultivator_summary.format_map(
                    {"境界": local.realm_name, "等级": local.level, "性别": local.gender, "状态": ""}
                ),
            )
    builder.section(
        copy.cultivators_visiting_section
        if result.space_type == "地表"
        else copy.cultivators_inside_section,
        icon=copy.navigation_icon,
    )
    if result.cultivators:
        for cultivator in result.cultivators:
            state = copy.state_separator.join(cultivator.states)
            summary = copy.cultivator_summary.format_map(
                {"境界": cultivator.realm_name, "等级": cultivator.level, "性别": cultivator.gender, "状态": ""},
            )
            direction = (
                copy.cultivator_direction.format_map(
                    {"方向": cultivator.direction, "距离": cultivator.distance}
                )
                if cultivator.direction
                else copy.colocated_cultivator_direction.format_map(
                    {"距离": cultivator.distance}
                )
            )
            builder.line(
                cultivator.name,
                " · ",
                summary,
                *(
                    (" · ", M.status(state, tone=_nearby_state_tone(state)))
                    if state
                    else ()
                ),
                " · ",
                direction,
            )
    else:
        builder.line(M.status("无人", tone="muted"), " ", copy.cultivators_empty)
    if result.page > 1 or result.has_next:
        builder.small(f"{copy.cultivators_page_section}：{result.page}")
    if result.truncated:
        builder.note(copy.cultivators_truncated)
    return builder.actions(message_actions(actions)).build()


def nearby_locations(
    copy: PositionCopy,
    result: NearbyWorldLocations,
    actions: tuple[CommandAction, ...],
):
    builder = (
        M.document()
        .header(copy.locations_title)
        .section(copy.locations_section, icon=copy.location_icon)
    )
    if not result.values:
        builder.line(M.status("空", tone="muted"), " ", copy.locations_empty)
    for index, location in enumerate(result.values, start=1):
        _append_location(builder, copy, index, location)
    return builder.actions(message_actions(actions)).build()


def error(
    copy: PositionCopy,
    title: str,
    message: str,
    actions: tuple[CommandAction, ...],
):
    return (
        M.document()
        .section(title, icon=copy.error_icon)
        .line(M.status("查询失败", tone="danger"), " ", message)
        .actions(message_actions(actions))
        .build()
    )


def _append_location(
    builder, copy: PositionCopy, index: int, location: NearbyWorldLocation
) -> None:
    functions = (
        copy.function_separator.join(location.functions) or copy.no_available_function
    )
    builder.item(
        index,
        copy.location_summary.format_map(
            {"名称": location.name, "方向": location.direction, "距离": location.distance}
        ),
    ).small(
        copy.location_detail.format_map(
            {"区域": location.region, "地形": location.terrain, "功能": functions}
        )
    )


def _location_name(copy: PositionCopy, location) -> str:
    if location.location_name:
        return location.location_name
    return copy.unknown_location.format_map({"区域": location.region, "地形": location.terrain})


def _coordinate(copy: PositionCopy, xy: tuple[int, int]) -> str:
    return copy.coordinate.format_map({"横坐标": xy[0], "纵坐标": xy[1]})


def _nearby_state_tone(value: str) -> str:
    if any(word in value for word in ("战斗", "重伤", "身死")):
        return "danger"
    if any(word in value for word in ("探险", "闭关", "采集", "托管")):
        return "warning"
    return "info"


__all__ = [
    "current",
    "error",
    "nearby_cultivators",
    "nearby_locations",
    "nearby_overview",
]
