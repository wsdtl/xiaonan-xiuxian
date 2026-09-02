from __future__ import annotations

from game.app import current_game_services
from game.features.butian import ButianConflictError, ButianError

from ...command import GameCommand
from . import reply


@GameCommand.command(
    cmd=("补天", "裂天原补天"),
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "炼制",
            "summary": "在裂天原为纯突破节点补入一项永久属性",
            "usage": ("补天 人物 炼气 140002", "补天 道侣 炼气 赤元聚气丹"),
            "side_effect": "消耗九霄补天丹并记录补正来源",
            "order": 71,
        },
    },
)
async def correct_breakthrough(
    *, user_id: str, message: str, message_context, manager, **_
) -> None:
    feature = current_game_services().features.butian
    parts = str(message or "").split()
    try:
        if len(parts) != 3:
            raise ButianError("格式：补天 人物或道侣 同境界 单属性突破丹编号")
        await manager.send(
            reply.result(
                feature,
                await feature.apply(
                    user_id, message_context.request_id, parts[0], parts[1], parts[2]
                ),
            )
        )
    except (ButianError, ButianConflictError) as exc:
        await manager.send(reply.error(feature, str(exc)))


__all__ = []
