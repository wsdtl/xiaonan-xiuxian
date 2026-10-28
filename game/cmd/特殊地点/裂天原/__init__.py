from __future__ import annotations

from game.app import current_game_services
from game.features.butian import ButianConflictError, ButianError

from ...command import GameCommand
from . import reply
from .site import router
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="补天",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "特殊地点",
            "summary": "在裂天原为纯突破节点补入一项永久属性",
            "usage": ("补天 人物 炼气 赤元聚气丹", "补天 道侣 炼气 赤元聚气丹"),
            "side_effect": "消耗九霄补天丹并记录补正来源",
            "order": 71,
        },
    },
)
async def correct_breakthrough(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.butian
    try:
        result = await feature.apply_from_text(
            user_id, message_context.request_id, message
        )
        await send_game_reply(
            reply.result(feature, result),
            title=f"补天 {result.medicine_name}",
        )
    except (ButianError, ButianConflictError) as exc:
        await send_game_reply(reply.error(feature, str(exc)), title="补天")


__all__ = ["router"]
