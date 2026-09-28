"""公开地图命令与只读地图页面。"""

from __future__ import annotations

from game.app import current_game_services
from launch.paths import public_url

from ...command import GameCommand
from . import reply
from .site import router
from typing import Any


@GameCommand.fullmatch(
    cmd="地图",
    metadata={
        "scope": "通用",
        "guard_rule": "始终可用",
        "help": {
            "category": "世界",
            "summary": "查看晓楠修仙界全境概况与公开舆图",
            "usage": ("地图",),
            "side_effect": "只读展示，不改变人物位置或世界状态",
            "order": 10,
        },
    },
)
async def show_world_map(manager: Any) -> None:
    overview = current_game_services().features.ditu.overview()
    await manager.send(reply.entry(overview, public_url("world-map")))


__all__ = ["router"]
