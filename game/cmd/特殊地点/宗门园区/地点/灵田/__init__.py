"""灵田：宗门园区的灵植生产地点。"""
from __future__ import annotations

from game.app import current_game_services

from .....command import GameCommand
from ... import production_common
from .site import router
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="灵田",
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "宗门",
            "summary": "查看或收取本宗灵田的随机灵植，并可选定一处地形（宗门园区）",
            "usage": (
                "灵田",
                "灵田 开启",
                "灵田 收取",
                "灵田 选地形",
                "灵田 选地形 地形名",
                "灵田 清地形",
            ),
            "side_effect": "查看只读；选定地形后灵田只产该地形的灵植，收取时按完整生产轮次统一写入本宗灵藏",
            "order": 83,
        },
    },
)
async def lingtian(
    user_id: str, message: str, message_context: MessageContext, manager: Any
) -> None:
    await production_common.dispatch(
        "灵田", user_id, str(message or "").strip(), message_context.request_id, manager
    )


__all__ = []
