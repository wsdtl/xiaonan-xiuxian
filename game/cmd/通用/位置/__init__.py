"""位置与附近对象二级组件命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.weizhi import NearbyPageError

from ...command import GameCommand
from . import reply
from typing import Any


@GameCommand.fullmatch(
    cmd=("位置", "山门"),
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "世界",
            "summary": "查看当前地点、地势与此地开放功能",
            "usage": ("位置", "山门"),
            "side_effect": "只查看，不会改变人物状态",
            "order": 20,
        },
    },
)
async def show_position(user_id: str, manager: Any) -> None:
    feature = current_game_services().features.weizhi
    services = current_game_services()
    result = await feature.current(user_id)
    gate_actions = await services.features.zongmen_shanmen.gate_actions(user_id)
    position_actions = feature.position_actions(
        result.location.available_functions,
        plant_pool=result.location.plant_pool,
        mineral_pool=result.location.mineral_pool,
    )
    await manager.send(
        reply.current(
            feature.copy(),
            result,
            position_actions + gate_actions,
        )
    )


@GameCommand.command(
    cmd="附近",
    metadata={
        "scope": "通用",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "世界",
            "summary": "查看附近地点或修士",
            "usage": ("附近", "附近 地点", "附近 修士", "附近 修士 页码"),
            "side_effect": "只查看，不会改变人物状态",
            "order": 30,
        },
    },
)
async def show_nearby(user_id: str, message: str, manager: Any) -> None:
    feature = current_game_services().features.weizhi
    copy = feature.copy()
    parts = str(message or "").split()
    if not parts:
        result = await feature.nearby_overview(user_id)
        await manager.send(
            reply.nearby_overview(
                copy,
                result,
                feature.nearby_overview_actions(
                    result.locations,
                    surface=result.current.space_type == "地表",
                ),
            )
        )
        return
    if parts == ["地点"]:
        result = await feature.nearby_locations(user_id)
        await manager.send(
            reply.nearby_locations(
                copy,
                result,
                feature.nearby_location_actions(result.values),
            )
        )
        return
    if parts[0] == "修士" and len(parts) <= 2:
        try:
            page = _page_number(parts[1], copy.invalid_page) if len(parts) == 2 else 1
            result = await feature.nearby_cultivators(user_id, page)
            await manager.send(
                reply.nearby_cultivators(
                    copy,
                    result,
                    feature.nearby_cultivator_actions(
                        result.page,
                        result.has_next,
                        surface=result.space_type == "地表",
                    ),
                )
            )
        except NearbyPageError as exc:
            await manager.send(
                reply.error(
                    copy,
                    copy.cultivators_title,
                    str(exc),
                    feature.nearby_overview_actions(),
                )
            )
        return
    await manager.send(
        reply.error(
            copy,
            copy.overview_title.format_map({"地点": "附近"}),
            copy.invalid_command,
            feature.format_actions(),
        )
    )


def _page_number(value: str, invalid_message: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise NearbyPageError(invalid_message) from exc



@GameCommand.command(
    cmd=("查看修士", "看修士"),
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "世界",
            "summary": "按名字或编号查看附近某个人的公开资料",
            "usage": ("查看修士 名字", "查看修士 500001"),
            "side_effect": "只查看，不会改变人物状态",
            "order": 40,
        },
    },
)
async def inspect_cultivator(user_id: str, message: str, manager: Any) -> None:
    query = " ".join(str(message or "").split())
    feature = current_game_services().features.weizhi
    copy = feature.copy()
    actions = feature.nearby_cultivator_actions(1, False)
    if not query:
        await manager.send(reply.error(copy, copy.cultivator_view, copy.cultivator_queriless, actions))
        return
    if len(query) == 6 and query.isdigit() and query[:2] == "50":
        view = await feature.inspect_companion(user_id, query)
        if view is None:
            await manager.send(
                reply.error(
                    copy,
                    copy.cultivator_view,
                    copy.cultivator_not_met.format_map({"编号": query}),
                    actions,
                )
            )
            return
        await manager.send(reply.companion(copy, view, actions))
        return
    profile = await feature.inspect_cultivator(user_id, query)
    if profile is None:
        await manager.send(reply.error(copy, copy.cultivator_view, copy.cultivator_missing, actions))
        return
    await manager.send(reply.cultivator(copy, profile, actions))

__all__ = []
