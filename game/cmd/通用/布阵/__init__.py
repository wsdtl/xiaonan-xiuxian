"""通用布阵命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.buzhen import FormationArmFeatureError

from ...command import GameCommand
from . import reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="布阵",
    metadata={
        "scope": "通用",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "战斗",
            "summary": "从阵藏取出一座阵法，备入下一场正式战斗",
            "usage": ("布阵 阵藏条目编号", "布阵 周天星斗大阵 黄"),
            "side_effect": "阵法离开阵藏并进入待战状态，一次只能准备一座",
            "order": 67,
        },
    },
)
async def arm_formation(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.buzhen
    query = str(message or "").strip()
    if not query:
        await manager.send(
            reply.error(feature.copy(), "格式：布阵 阵藏条目编号或阵法名称 品级")
        )
        return
    try:
        value = await feature.arm(user_id, message_context.request_id, query)
        await manager.send(reply.completed(feature.copy(), value))
    except FormationArmFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


__all__ = []
