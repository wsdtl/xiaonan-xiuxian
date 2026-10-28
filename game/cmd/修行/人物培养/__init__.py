"""人物培养通用命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.renwu_peiyang import (
    CharacterBreakthroughRequest,
    CharacterCultivationConflictError,
    CharacterCultivationFeatureError,
)

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.fullmatch(
    cmd="人物培养",
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "修行",
            "summary": "查看人物修为、修行槽与本命武器培养状态",
            "usage": ("人物培养",),
            "side_effect": "只查看，不会改变人物状态",
            "order": 10,
        },
    },
)
async def show_character_cultivation(user_id: str, manager: Any) -> None:
    feature = current_game_services().features.renwu_peiyang
    try:
        result = await feature.inspect(user_id)
        await send_game_reply(reply.view(feature, result))
    except CharacterCultivationFeatureError as exc:
        await send_game_reply(reply.error(feature, str(exc), feature.format_actions()))


@GameCommand.command(
    cmd="人物突破",
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "修行",
            "summary": "消耗对应突破丹为人物突破境界",
            "usage": ("人物突破 小还丹", "人物突破 丹药编号或名称",),
            "side_effect": "消耗纳戒中最低品级的一枚对应突破丹；须当前境界已满级且该境界还没突破过，突破抬高意境阶上限时会顺带发道行",
            "order": 30,
        },
    },
)
async def breakthrough_character(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.renwu_peiyang
    try:
        result = await feature.breakthrough(
            CharacterBreakthroughRequest(
                user_id, message_context.request_id, message.strip()
            )
        )
        await send_game_reply(
            reply.breakthrough(feature, result),
            title=f"人物突破 {result.medicine_name}",
        )
    except (CharacterCultivationFeatureError, CharacterCultivationConflictError) as exc:
        # 名字写错时别让人猜：把本境界的候选丹一并端出来（算不出来就照旧只报错）。
        try:
            offer = await feature.breakthrough_offer(user_id)
        except (CharacterCultivationFeatureError, CharacterCultivationConflictError):
            offer = None
        await send_game_reply(
            reply.error(feature, str(exc), feature.format_actions(), offer),
            title="人物突破",
        )


__all__ = []
