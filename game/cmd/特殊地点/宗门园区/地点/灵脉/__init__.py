"""灵脉：宗门园区的灵石/灵矿生产地点。"""
from __future__ import annotations

from game.app import current_game_services

from .....command import GameCommand
from .. import production_common
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="灵脉",
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "宗门",
            "summary": "查看或收取本宗灵脉的随机灵石与灵矿（宗门园区）",
            "usage": ("灵脉", "灵脉 开启", "灵脉 收取"),
            "side_effect": "查看只读；开启与收取限宗主或长老，收取时按完整生产轮次统一写入本宗灵藏",
            "order": 82,
        },
    },
)
async def lingmai(
    user_id: str, message: str, message_context: MessageContext, manager: Any
) -> None:
    await production_common.dispatch(
        "灵脉", user_id, str(message or "").strip(), message_context.request_id, manager
    )


__all__ = []
