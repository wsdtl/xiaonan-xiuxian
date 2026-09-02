from __future__ import annotations

from game.app import current_game_services
from game.features.yixing import YixingConflictError, YixingError

from ...command import GameCommand
from . import reply


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
async def change_gender(*, user_id: str, message_context, manager, **_) -> None:
    feature = current_game_services().features.yixing
    try:
        await manager.send(
            reply.result(
                feature, await feature.change(user_id, message_context.request_id)
            )
        )
    except (YixingError, YixingConflictError) as exc:
        await manager.send(reply.error(feature, str(exc)))


__all__ = []
