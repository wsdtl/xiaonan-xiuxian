"""宗门洞天专属藏经阁命令。"""
from __future__ import annotations

from game.app import current_game_services
from game.features.zongmen_cangjing import CangjingFeatureError

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="藏经阁",
    metadata={
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "宗门",
            "summary": "在宗门园区藏经阁查阅、借阅本宗共享功法",
            "usage": (
                "藏经阁",
                "藏经阁 2",
                "藏经阁 借阅 五朵金花功法",
                "藏经阁 借阅 五朵金花功法 1",
            ),
            "side_effect": "只读查阅；借阅替换人物指定功法槽，离开洞天后仍生效，离宗时恢复原功法",
            "order": 85,
        },
    },
)
async def cangjing(
    user_id: str, message: str, message_context: MessageContext, manager: Any
) -> None:
    feature = current_game_services().features.zongmen_cangjing
    copy = feature.copy()
    try:
        entry = await feature.enter(
            user_id, message_context.request_id, message
        )
    except CangjingFeatureError as exc:
        await send_game_reply(reply.error(copy, str(exc)))
        return
    if entry.kind == "page" and entry.page is not None:
        await send_game_reply(
            reply.page(copy, entry.page, feature.page_actions(entry.page))
        )
    elif entry.kind == "prompt":
        await send_game_reply(
            reply.borrow_prompt(
                copy, entry.identifier, range(1, entry.slots + 1)
            )
        )
    elif entry.kind == "borrowed" and entry.borrowed is not None:
        await send_game_reply(reply.borrowed(copy, entry.borrowed))


__all__ = []
