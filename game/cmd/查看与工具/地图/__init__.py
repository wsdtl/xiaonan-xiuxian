"""公开地图命令与只读地图页面。"""

from __future__ import annotations

from game.app import current_game_services
from launch.paths import public_url

from ...command import GameCommand
from . import reply
from .site import router
from ...reply_composer import send_game_reply
from typing import Any


@GameCommand.command(
    cmd="地图",
    metadata={
        "scope": "通用",
        "guard_rule": "始终可用",
        "help": {
            "category": "查看与工具",
            "summary": "查看晓楠修仙界的大区域与地点，或打开公开舆图",
            "usage": ("地图", "地图 州名"),
            "side_effect": "只读展示，不改变人物位置或世界状态",
            "order": 10,
        },
    },
)
async def show_world_map(user_id: str, message: str, manager: Any) -> None:
    overview = current_game_services().features.ditu.overview()
    url = public_url("world-map")
    query = " ".join(str(message or "").split())
    if query:
        # 参数是**州名**（不再是页码）：州名不认识时 reply 会给提示卡。
        await send_game_reply(reply.region(overview, query, url))
        return
    await send_game_reply(reply.entry(overview, url))


__all__ = ["router"]
