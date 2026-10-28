from __future__ import annotations

from game.app import current_game_services
from game.features.fanben import FanbenConflictError, FanbenError
from game.features.yixing import YixingConflictError, YixingError

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="易形",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "特殊地点",
            "summary": "在太素坊改变玩家自身性别",
            "usage": ("易形",),
            "side_effect": "消耗一枚两仪易形丹；已有道侣关系保持不变",
            "order": 72,
        },
    },
)
async def change_gender(user_id: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.yixing
    try:
        result = await feature.change(user_id, message_context.request_id)
        await send_game_reply(
            reply.result(feature, result),
            title=f"易形 {result.gender_after}",
        )
    except (YixingError, YixingConflictError) as exc:
        await send_game_reply(reply.error(feature, str(exc)), title="易形")


@GameCommand.command(
    cmd="化形",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "特殊地点",
            "summary": "在太素坊择一族重塑种族",
            "usage": ("化形 人族", "化形 <族名>"),
            "side_effect": "消耗一枚万化易形丹；修行、构筑与道侣关系保持不变",
            "order": 73,
        },
    },
)
async def reshape_race(
    user_id: str, message: str, message_context: MessageContext, manager: Any
) -> None:
    feature = current_game_services().features.fanben
    # 族名不含空格，整段去掉命令词后的文本就是目标种族。
    wanted = " ".join(str(message or "").split())
    try:
        result = await feature.change(
            user_id, message_context.request_id, wanted
        )
        await send_game_reply(
            reply.fanben_result(feature, result),
            title=f"化形 {result.race_after}",
        )
    except (FanbenError, FanbenConflictError) as exc:
        await send_game_reply(reply.fanben_error(feature, str(exc)), title="化形")


__all__ = []
