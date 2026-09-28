"""玩家通用切磋命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.qiecuo import DuelError, DuelStartCommand

from ...command import GameCommand
from . import reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="切磋",
    metadata={
        "scope": "通用",
        "guard_rule": "自主空闲或休息且可行动",
        "help": {
            "category": "战斗",
            "summary": "向附近玩家及其同行编组发起切磋",
            "usage": ("切磋 玩家编号或姓名",),
            "side_effect": "发送切磋邀约，不立即改变正式资源",
            "order": 80,
        },
    },
)
async def start(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.qiecuo
    try:
        target = await feature.resolve_target(user_id, message)
        target_name = await feature.target_name(target)
        value = await feature.start(
            DuelStartCommand(user_id, target, message_context.request_id)
        )
        await manager.send(reply.challenge(feature, value, target_name))
    except (DuelError, ValueError) as exc:
        await manager.send(reply.error(feature, str(exc)))


@GameCommand.command(
    cmd="接受切磋",
    metadata={
        "scope": "通用",
        "guard_rule": "自主空闲或休息且可行动",
        "help": {
            "category": "战斗",
            "summary": "接受附近玩家发来的切磋邀约",
            "usage": ("接受切磋",),
            "side_effect": "执行一次不影响正式资源的切磋并生成战报",
            "order": 81,
        },
    },
)
async def accept(user_id: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.qiecuo
    try:
        value = await feature.accept(user_id, message_context.request_id)
        challenger_name = await feature.target_name(value.user_participants[0])
        target_name = await feature.target_name(value.target_participants[0])
        await manager.send(reply.result(feature, value, challenger_name, target_name))
    except (DuelError, ValueError) as exc:
        await manager.send(reply.error(feature, str(exc)))


@GameCommand.command(
    cmd="拒绝切磋",
    metadata={
        "scope": "通用",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "战斗",
            "summary": "拒绝待处理的切磋邀约",
            "usage": ("拒绝切磋",),
            "side_effect": "清除待处理邀约",
            "order": 82,
        },
    },
)
async def reject(user_id: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.qiecuo
    try:
        await feature.reject(user_id, message_context.request_id)
        await manager.send(reply.rejected())
    except (DuelError, ValueError) as exc:
        await manager.send(reply.error(feature, str(exc)))
