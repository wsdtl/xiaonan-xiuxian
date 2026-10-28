from __future__ import annotations

from game.app import current_game_services
from game.features.xigen import XigenConflictError, XigenError

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="洗根",
    metadata={
        'scope': '专属',
        'guard_rule': '空闲或活动中',
        'help': {
            'category': '特殊地点',
            'summary': '在归元观重掷自己的五行根性',
            'usage': ('洗根',),
            'side_effect': '消耗一枚灵根重铸丹；修行、构筑、种族与道侣关系保持不变',
            'order': 74,
        },
    },
)
async def reroll_elements(user_id: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.xigen
    try:
        await send_game_reply(
            reply.xigen_result(
                feature, await feature.change(user_id, message_context.request_id)
            )
        )
    except (XigenError, XigenConflictError) as exc:
        await send_game_reply(reply.xigen_error(feature, str(exc)))


__all__ = []
