"""通用布阵命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.buzhen import FormationArmFeatureError, FormationChoiceError

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="布阵",
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "战斗",
            "summary": "从阵藏取出一座阵法，备入下一场正式战斗",
            "usage": ("布阵 黄品叠翠盘根阵", "布阵 <品级><阵法名>[灵宝]"),
            "side_effect": "阵法离开阵藏并进入待战状态，一次只能准备一座",
            "order": 67,
        },
    },
)
async def arm_formation(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.buzhen
    query = str(message or "").strip()
    if not query:
        await send_game_reply(
            reply.error(feature.copy(), "格式：布阵 <品级><阵法名>[灵宝]")
        )
        return
    try:
        value = await feature.arm(user_id, message_context.request_id, query)
        await send_game_reply(
            reply.completed(feature.copy(), value, value.prepared.treasure_line)
        )
    except FormationChoiceError as exc:
        await send_game_reply(reply.choose(feature.copy(), exc))
    except FormationArmFeatureError as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc)))


__all__ = []
