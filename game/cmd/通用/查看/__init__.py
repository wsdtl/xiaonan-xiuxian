"""查看类命令入口。"""

from __future__ import annotations

from game.app import current_game_services
from launch.paths import public_url

from ...command import GameCommand
from . import reply
from .site import router
from typing import Any


@GameCommand.command(
    cmd="查看",
    metadata={
        "scope": "通用",
        "guard_rule": "始终可用",
        "help": {
            "category": "资源",
            "summary": "按编号或名称查看物品、功法、道侣等详细资料",
            "usage": ("查看 编号", "查看 名称"),
            "side_effect": "只读查询，不改变人物、背包或世界状态",
            "order": 10,
        },
    },
)
async def inspect_entity(user_id: str, message: str, manager: Any) -> None:
    query = " ".join(str(message or "").split())
    if not query:
        await manager.send(reply.missing_query())
        return

    result = await current_game_services().features.chakan_wupin.inspect(query, user_id)
    await manager.send(reply.inspection(result, public_url("baike")))


__all__ = ["router"]
