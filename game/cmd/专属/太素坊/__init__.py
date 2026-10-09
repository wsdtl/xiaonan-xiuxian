from __future__ import annotations

from game.app import current_game_services
from game.features.fanben import FanbenConflictError, FanbenError
from game.features.yixing import YixingConflictError, YixingError

from ...command import GameCommand
from . import reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd=("易形", "太素坊易形"),
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "炼制",
            "summary": "在太素坊改变玩家自身性别",
            "usage": ("易形", "太素坊易形"),
            "side_effect": "消耗一枚两仪易形丹；已有道侣关系保持不变",
            "order": 72,
        },
    },
)
async def change_gender(user_id: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.yixing
    try:
        await manager.send(
            reply.result(
                feature, await feature.change(user_id, message_context.request_id)
            )
        )
    except (YixingError, YixingConflictError) as exc:
        await manager.send(reply.error(feature, str(exc)))


@GameCommand.command(
    cmd=("返本", "太素坊返本"),
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "炼制",
            "summary": "在太素坊把人物种族转为人族",
            "usage": ("返本", "太素坊返本"),
            "side_effect": "消耗一枚返本还元丹；修行、构筑与道侣关系保持不变",
            "order": 73,
        },
    },
)
async def restore_race(user_id: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.fanben
    try:
        await manager.send(
            reply.fanben_result(
                feature, await feature.change(user_id, message_context.request_id)
            )
        )
    except (FanbenError, FanbenConflictError) as exc:
        await manager.send(reply.fanben_error(feature, str(exc)))


__all__ = []
