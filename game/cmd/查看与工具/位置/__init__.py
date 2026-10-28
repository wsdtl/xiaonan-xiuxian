"""位置与附近对象二级组件命令。"""

from __future__ import annotations

from game.app import current_game_services

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from typing import Any


@GameCommand.fullmatch(
    cmd="位置",
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "查看与工具",
            "summary": "查看当前地点、地势与此地开放功能",
            "usage": ("位置",),
            "side_effect": "只查看，不会改变人物状态",
            "order": 20,
        },
    },
)
async def show_position(user_id: str, manager: Any) -> None:
    feature = current_game_services().features.weizhi
    result = await feature.current(user_id)
    position_actions = feature.position_actions(result.location)
    await send_game_reply(
        reply.current(
            feature.copy(),
            result,
            position_actions,
        )
    )


@GameCommand.command(
    cmd="附近",
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "查看与工具",
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
    entry = await feature.nearby_enter(user_id, message)
    if entry.kind == "overview" and entry.overview is not None:
        await send_game_reply(
            reply.nearby_overview(
                copy,
                entry.overview,
                feature.nearby_overview_actions(
                    entry.overview.locations,
                    surface=entry.overview.current.space_type == "地表",
                ),
            )
        )
    elif entry.kind == "locations" and entry.locations is not None:
        await send_game_reply(
            reply.nearby_locations(
                copy,
                entry.locations,
                feature.nearby_location_actions(entry.locations.values),
            )
        )
    elif entry.kind == "cultivators" and entry.cultivators is not None:
        await send_game_reply(
            reply.nearby_cultivators(
                copy,
                entry.cultivators,
                feature.nearby_cultivator_actions(
                    entry.cultivators.page,
                    entry.cultivators.has_next,
                    surface=entry.cultivators.space_type == "地表",
                ),
            )
        )
    else:
        await send_game_reply(
            reply.error(
                copy,
                entry.error_title,
                entry.error_message,
                feature.nearby_overview_actions(),
            )
        )


__all__ = []
