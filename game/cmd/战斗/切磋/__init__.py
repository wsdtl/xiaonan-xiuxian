"""玩家通用切磋命令。"""

from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.qiecuo import DuelError, DuelStartCommand

from ...command import GameCommand
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from . import reply


@GameCommand.command(
    cmd="切磋",
    metadata={
        "scope": "通用",
        "guard_rule": "自主空闲或休息且可行动",
        "help": {
            "category": "战斗",
            "summary": "向任意玩家及其当前同行编组发起切磋；接受时按实际名单开战",
            "usage": (
                "切磋 云中鹤",
                "切磋 接受",
                "切磋 拒绝",
                "切磋 撤回",
            ),
            "side_effect": "发送切磋邀约（300 秒内有效，一个玩家同时只能有一条）；接受后立即开战，不改变正式资源",
            "order": 80,
        },
    },
)
async def start(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    action = str(message or "").strip()
    handler = {
        "接受": _accept,
        "拒绝": _reject,
        "撤回": _withdraw,
    }.get(action)
    if handler is not None:
        await handler(user_id, message_context, manager)
        return
    feature = current_game_services().features.qiecuo
    try:
        target = await feature.resolve_target(user_id, action)
        target_name = await feature.target_name(target)
        value = await feature.start(
            DuelStartCommand(user_id, target, message_context.request_id)
        )
        await send_game_reply(
            reply.challenge(feature, value, target_name),
            title=f"切磋 {target_name}",
        )
    except (DuelError, ValueError) as exc:
        await send_game_reply(
            reply.error(feature, str(exc), feature.format_actions()),
            title="切磋",
        )


async def _accept(user_id: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.qiecuo
    try:
        value = await feature.accept(user_id, message_context.request_id)
        challenger_name = await feature.target_name(value.user_participants[0])
        target_name = await feature.target_name(value.target_participants[0])
        await send_game_reply(reply.result(feature, value, challenger_name, target_name))
    except (DuelError, ValueError) as exc:
        await send_game_reply(reply.error(feature, str(exc), feature.format_actions()))


async def _reject(user_id: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.qiecuo
    try:
        await feature.reject(user_id, message_context.request_id)
        await send_game_reply(reply.rejected())
    except (DuelError, ValueError) as exc:
        await send_game_reply(reply.error(feature, str(exc), feature.format_actions()))


async def _withdraw(user_id: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.qiecuo
    try:
        value = await feature.withdraw(user_id, message_context.request_id)
        target_name = await feature.target_name(value.target_user_id)
        await send_game_reply(reply.withdrawn(target_name))
    except (DuelError, ValueError) as exc:
        await send_game_reply(reply.error(feature, str(exc), feature.format_actions()))


__all__ = []
