from __future__ import annotations

from game.app import current_game_services
from game.features.guiyuan import GuiyuanConflictError, GuiyuanError
from game.features.xigen import XigenConflictError, XigenError

from ...command import GameCommand
from . import reply
from .site import router
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="归元",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "特殊地点",
            "summary": "在归元观重做同行道侣的一类构筑",
            "usage": ("归元", "归元 功法", "归元 真意", "归元 气机"),
            "side_effect": "消耗一枚万法归元丹并重抽所选类别",
            "order": 70,
        },
    },
)
async def reset_build(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.guiyuan
    query = str(message or "").strip()
    try:
        if not query:
            await send_game_reply(reply.preview(feature, await feature.preview(user_id)))
        else:
            await send_game_reply(
                reply.result(
                    feature,
                    await feature.reset(user_id, message_context.request_id, query),
                )
            )
    except (GuiyuanError, GuiyuanConflictError) as exc:
        await send_game_reply(reply.error(feature, str(exc)))


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


__all__ = ["router"]
