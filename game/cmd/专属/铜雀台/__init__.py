"""铜雀台地点专属夺元命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.tongquetai import (
    TongquetaiConflictError,
    TongquetaiError,
    TongquetaiRequest,
)

from ...command import GameCommand
from . import reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd=("夺元", "铜雀台夺元"),
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "道侣",
            "summary": "在铜雀台预览或执行同行道侣修为归流",
            "usage": ("夺元", "夺元 护契", "夺元 离契"),
            "side_effect": "护契消耗守真定契丹；离契使好感归零并解除同行",
            "order": 60,
        },
    },
)
async def transfer_cultivation(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.tongquetai
    mode = str(message or "").strip()
    try:
        if not mode:
            value = await feature.preview(user_id)
            await manager.send(reply.preview(feature, value))
            return
        if mode not in {"护契", "离契"}:
            raise TongquetaiError(feature.copy("错误", "格式"))
        value = await feature.settle(
            TongquetaiRequest(user_id, message_context.request_id, mode)
        )
        await manager.send(reply.settled(feature, value))
    except (TongquetaiError, TongquetaiConflictError) as exc:
        await manager.send(reply.error(feature, str(exc)))


__all__ = []
