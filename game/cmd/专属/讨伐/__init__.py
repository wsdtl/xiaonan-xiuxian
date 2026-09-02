"""地点专属讨伐命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.taofa import RaidFeatureError

from ...command import GameCommand
from . import reply


@GameCommand.fullmatch(
    cmd=("开始讨伐", "讨伐"),
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲且可行动",
        "help": {
            "category": "行动",
            "summary": "在当前北方城池发起讨伐",
            "usage": ("开始讨伐", "讨伐"),
            "side_effect": "预先锁定敌方编组并进入讨伐中",
            "order": 36,
        },
    },
)
async def start_raid(*, user_id: str, message_context, manager, **_) -> None:
    feature = current_game_services().features.taofa
    try:
        value = await feature.start(user_id, message_context.request_id)
        await manager.send(reply.started(feature, value))
    except RaidFeatureError as exc:
        await manager.send(reply.error(feature, str(exc)))


@GameCommand.fullmatch(
    cmd=("讨伐战况", "查看讨伐战况", "讨况"),
    metadata={
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "查看讨伐剩余时间和首领血段",
            "usage": ("讨伐战况", "查看讨伐战况", "讨况"),
            "side_effect": "只读查询",
            "order": 37,
        },
    },
)
async def raid_progress(*, user_id: str, manager, **_) -> None:
    feature = current_game_services().features.taofa
    try:
        value = await feature.progress(user_id)
        await manager.send(reply.progress(feature, value))
    except RaidFeatureError as exc:
        await manager.send(reply.error(feature, str(exc)))


@GameCommand.fullmatch(
    cmd=("讨伐结束", "结算讨伐", "讨伐结算", "结束讨伐", "讨结"),
    metadata={
        "hosting": {"activity": "讨伐", "phase": "end"},
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "讨伐结束后结算奖励",
            "usage": ("讨伐结束", "结算讨伐", "讨伐结算", "结束讨伐", "讨结"),
            "side_effect": "发放奖励并释放讨伐状态",
            "order": 38,
        },
    },
)
async def raid_settle(*, user_id: str, message_context, manager, **_) -> None:
    feature = current_game_services().features.taofa
    try:
        value = await feature.settle(user_id, message_context.request_id)
        await manager.send(reply.settlement(feature, value))
    except RaidFeatureError as exc:
        await manager.send(reply.error(feature, str(exc)))


__all__ = []
