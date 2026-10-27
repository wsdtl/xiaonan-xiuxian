"""当前同行道侣培养通用命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.daolv_peiyang import (
    CompanionBreakthroughRequest,
    CompanionCultivationConflictError,
    CompanionCultivationFeatureError,
)

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.fullmatch(
    cmd="道侣培养",
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "修行",
            "summary": "查看当前同行道侣的独立成长与本命武器",
            "usage": ("道侣培养",),
            "side_effect": "只读查询，不重新随机道侣构筑",
            "order": 50,
        },
    },
)
async def show_companion_cultivation(user_id: str, manager: Any) -> None:
    feature = current_game_services().features.daolv_peiyang
    try:
        result = await feature.inspect(user_id)
        await send_game_reply(reply.view(feature, result))
    except CompanionCultivationFeatureError as exc:
        await send_game_reply(reply.error(feature, str(exc), feature.format_actions()))


@GameCommand.command(
    cmd="道侣突破",
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "修行",
            "summary": "消耗突破丹为当前同行道侣独立突破",
            "usage": ("道侣突破 小还丹", "道侣突破 丹药编号或名称",),
            "side_effect": "消耗共享纳戒中最低品级的一枚对应突破丹；须当前同行道侣已满级且该境界还没突破过",
            "order": 60,
        },
    },
)
async def breakthrough_companion(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.daolv_peiyang
    try:
        result = await feature.breakthrough(
            CompanionBreakthroughRequest(
                user_id, message_context.request_id, message.strip()
            )
        )
        await send_game_reply(reply.breakthrough(feature, result))
    except (CompanionCultivationFeatureError, CompanionCultivationConflictError) as exc:
        # 与人物突破同款：名字写错时把本境界的候选丹一并端出来。
        try:
            offer = await feature.breakthrough_offer(user_id)
        except (CompanionCultivationFeatureError, CompanionCultivationConflictError):
            offer = None
        await send_game_reply(
            reply.error(feature, str(exc), feature.format_actions(), offer)
        )


__all__ = []
