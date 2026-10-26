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
    parts = str(message or "").strip().split(maxsplit=1)
    try:
        if not parts:
            await _page(feature, user_id, 1, manager)
            return
        action = parts[0]
        rest = parts[1].strip() if len(parts) > 1 else ""
        if action.isdecimal():
            await _page(feature, user_id, _positive(action, "藏经阁页码"), manager)
            return
        if action == "借阅":
            await _borrow(feature, user_id, rest, message_context, manager)
            return
        raise CangjingFeatureError(copy.text["分支"])
    except CangjingFeatureError as exc:
        await send_game_reply(reply.error(copy, str(exc)))


async def _page(feature: Any, user_id: str, page: int, manager: Any) -> None:
    value = await feature.page(user_id, page)
    await send_game_reply(reply.page(feature.copy(), value, feature.page_actions(value)))


async def _borrow(
    feature: Any,
    user_id: str,
    rest: str,
    message_context: MessageContext,
    manager: Any,
) -> None:
    copy = feature.copy()
    words = rest.split()
    if not words:
        raise CangjingFeatureError(copy.text["借阅写法"])
    identifier = words[0]
    if len(words) == 1:
        slots = await feature.borrow_slots(user_id)
        if slots < 1:
            raise CangjingFeatureError("没有可用的功法槽")
        await send_game_reply(reply.borrow_prompt(copy, identifier, range(1, slots + 1)))
        return
    if len(words) != 2:
        raise CangjingFeatureError(copy.text["借阅写法"])
    slot = _positive(words[1], "功法槽位")
    value = await feature.borrow(
        user_id, message_context.request_id, identifier, slot
    )
    await send_game_reply(reply.borrowed(copy, value))


def _positive(value: str, label: str) -> int:
    if not value.isdecimal() or int(value) < 1:
        raise CangjingFeatureError(f"{label}必须是正整数")
    return int(value)


__all__ = []
