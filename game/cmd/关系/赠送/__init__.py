"""玩家通用赠送命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.presentation import ItemRefError
from game.features.zengsong import GiftError

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="赠送",
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "关系",
            "summary": "向指定玩家赠送灵石或基础物资（可按用户编号跨地点名送达）",
            "usage": ("赠送 云中鹤 灵石 100", "赠送 玩家 灵石 数量", "赠送 玩家 黄品小还丹 3", "赠送 玩家 <品级><物品> 数量"),
            "side_effect": "一次扣清、一次到账，不留下半途状态；单次数量上限 1 亿",
            "order": 83,
        },
    },
)
async def send(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.zengsong
    try:
        entry = await feature.enter(
            user_id, message_context.request_id, message
        )
        if entry.kind == "stones":
            await send_game_reply(
                reply.stones(feature, entry.target_name, entry.result)
            )
        else:
            await send_game_reply(
                reply.item(
                    feature,
                    entry.target_name,
                    entry.result,
                    grade_name=entry.result.grade_name,
                    item_name=entry.result.item_name,
                )
            )
    except (GiftError, ValueError, ItemRefError) as exc:
        await send_game_reply(reply.error(feature, str(exc), feature.format_actions()))
