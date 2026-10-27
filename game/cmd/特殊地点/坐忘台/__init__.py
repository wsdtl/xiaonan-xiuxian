"""坐忘台二级组件命令。"""

from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.yijing import YijingConflictError, YijingError
from launch.adapter import MessageContext

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply


@GameCommand.command(
    cmd="坐忘",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "特殊地点",
            "summary": "在坐忘台服下忘境丹，把六条意境抹去、道行退回重排",
            "usage": ("坐忘",),
            "side_effect": "消耗一枚忘境丹；六条意境练过的阶全部清零，道行退回到已发总额",
            "order": 76,
        },
    },
)
async def zuowang(user_id: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.yijing
    try:
        await send_game_reply(
            reply.refund_result(
                feature, await feature.refund(user_id, message_context.request_id)
            )
        )
    except (YijingError, YijingConflictError) as exc:
        await send_game_reply(reply.refund_error(feature, str(exc)))


__all__ = []
