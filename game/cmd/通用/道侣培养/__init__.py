"""当前同行道侣培养通用命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.daolv_peiyang import (
    CompanionBreakthroughRequest,
    CompanionCultivationConflictError,
    CompanionCultivationFeatureError,
    CompanionLawRequest,
)

from ...command import GameCommand
from . import reply


@GameCommand.fullmatch(
    cmd="道侣培养",
    metadata={
        "scope": "通用",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "修行",
            "summary": "查看当前同行道侣的独立成长与本命武器",
            "usage": ("道侣培养",),
            "side_effect": "只读查询，不重新随机道侣构筑",
            "order": 50,
        },
    },
)
async def show_companion_cultivation(*, user_id: str, manager, **_) -> None:
    feature = current_game_services().features.daolv_peiyang
    try:
        result = await feature.inspect(user_id)
        await manager.send(reply.view(feature, result))
    except CompanionCultivationFeatureError as exc:
        await manager.send(reply.error(str(exc)))


@GameCommand.command(
    cmd="道侣突破",
    metadata={
        "scope": "通用",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "修行",
            "summary": "消耗突破丹为当前同行道侣独立突破",
            "usage": ("道侣突破 丹药编号或名称",),
            "side_effect": "消耗共享纳戒中最低品级的一枚对应突破丹",
            "order": 60,
        },
    },
)
async def breakthrough_companion(
    *, user_id: str, message: str, message_context, manager
) -> None:
    feature = current_game_services().features.daolv_peiyang
    try:
        result = await feature.breakthrough(
            CompanionBreakthroughRequest(
                user_id, message_context.request_id, message.strip()
            )
        )
        await manager.send(reply.breakthrough(feature, result))
    except (CompanionCultivationFeatureError, CompanionCultivationConflictError) as exc:
        await manager.send(reply.error(str(exc)))


@GameCommand.command(
    cmd="道侣覆炼",
    metadata={
        "scope": "通用",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "修行",
            "summary": "把器藏中的器律覆入当前同行道侣本命武器",
            "usage": ("道侣覆炼 器律编号或名称 孔位",),
            "side_effect": "消耗器藏中的一份器律并覆盖道侣武器指定孔位",
            "order": 70,
        },
    },
)
async def forge_companion_law(
    *, user_id: str, message: str, message_context, manager
) -> None:
    feature = current_game_services().features.daolv_peiyang
    parts = message.rsplit(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdecimal():
        await manager.send(reply.error("格式：道侣覆炼 器律编号或名称 孔位"))
        return
    try:
        result = await feature.forge_law(
            CompanionLawRequest(
                user_id,
                message_context.request_id,
                parts[0],
                int(parts[1]),
            )
        )
        await manager.send(reply.forged(feature, result))
    except (CompanionCultivationFeatureError, CompanionCultivationConflictError) as exc:
        await manager.send(reply.error(str(exc)))


__all__ = []
