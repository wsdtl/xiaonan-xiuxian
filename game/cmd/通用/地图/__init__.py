"""公开地图命令与只读地图页面。"""

from __future__ import annotations

from game.app import current_game_services
from launch.paths import public_url

from ...command import GameCommand
from . import reply
from .site import router
from typing import Any


@GameCommand.command(
    cmd="地图",
    metadata={
        "scope": "通用",
        "guard_rule": "始终可用",
        "help": {
            "category": "世界",
            "summary": "按区域分页查看晓楠修仙界全部地点，或打开公开舆图",
            "usage": ("地图", "地图 页码"),
            "side_effect": "只读展示，不改变人物位置或世界状态",
            "order": 10,
        },
    },
)
async def show_world_map(user_id: str, message: str, manager: Any) -> None:
    overview = current_game_services().features.ditu.overview()
    url = public_url("world-map")
    query = " ".join(str(message or "").split())
    if query.isdigit() and len(query) <= 2:
        index = int(query)
        if not 1 <= index <= len(overview.regions):
            await manager.send(reply.invalid_page(overview, url))
            return
        await manager.send(reply.entry(overview, url, index))
        return
    await manager.send(reply.entry(overview, url))


__all__ = ["router"]
