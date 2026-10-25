"""演阵台：宗门园区的炼阵地点。"""
from __future__ import annotations

from game.app import current_game_services

from .....command import GameCommand
from ... import refining_common
from .site import router
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="演阵台",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "炼制",
            "summary": "在演阵台炼制一次性阵法（宗门园区）",
            "usage": (
                "演阵台",
                "演阵台 宗门",
                "演阵台 1",
                "演阵台 黄品叠翠盘根阵",
                "演阵台 炼阵 圣品叠翠盘根阵 100 200 300",
            ),
            "side_effect": "按次消耗宗门灵石；黄玄地天按固定配方，圣品三相投入为总数（最低 28/56/42）且无上限",
            "order": 76,
        },
    },
)
async def yanzhantai(
    user_id: str, message: str, message_context: MessageContext, manager: Any
) -> None:
    await refining_common.dispatch(
        "炼阵", user_id, str(message or "").strip(), message_context.request_id, manager
    )


__all__ = []
