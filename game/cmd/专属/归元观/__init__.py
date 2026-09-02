from __future__ import annotations

from game.app import current_game_services
from game.features.guiyuan import GuiyuanConflictError, GuiyuanError

from ...command import GameCommand
from . import reply


@GameCommand.command(
    cmd=("归元", "归元观归元"),
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "炼制",
            "summary": "在归元观重做同行道侣的一类构筑",
            "usage": ("归元", "归元 功法", "归元 真意", "归元 气机", "归元观归元 功法"),
            "side_effect": "消耗一枚万法归元丹并重抽所选类别",
            "order": 70,
        },
    },
)
async def reset_build(
    *, user_id: str, message: str, message_context, manager, **_
) -> None:
    feature = current_game_services().features.guiyuan
    query = str(message or "").strip()
    try:
        if not query:
            await manager.send(reply.preview(feature, await feature.preview(user_id)))
        else:
            await manager.send(
                reply.result(
                    feature,
                    await feature.reset(user_id, message_context.request_id, query),
                )
            )
    except (GuiyuanError, GuiyuanConflictError) as exc:
        await manager.send(reply.error(feature, str(exc)))


__all__ = []
