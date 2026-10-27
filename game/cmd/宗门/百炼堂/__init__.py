"""百炼堂：宗门园区的炼器地点。"""
from __future__ import annotations

from game.app import current_game_services

from ...command import GameCommand
from .. import refining_common
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="百炼堂",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "宗门",
            "summary": "在百炼堂炼制本命武器器律（宗门园区）",
            "usage": ("百炼堂", "百炼堂 宗门", "百炼堂 灵器", "百炼堂 玄品无归劫锋"),
            "side_effect": "按次消耗宗门灵石；材料来源按个人或宗门路径结算；走宗门材料与炼制圣品限宗主或长老",
            "order": 74,
        },
    },
)
async def bailiantang(
    user_id: str, message: str, message_context: MessageContext, manager: Any
) -> None:
    await refining_common.dispatch(
        "炼器", user_id, str(message or "").strip(), message_context.request_id, manager
    )


__all__ = []
