from __future__ import annotations

from game.app import current_game_services
from game.features.duihuan import DuihuanConflictError, DuihuanError

from ...command import GameCommand
from . import reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd=('兑换', '兑换码'),
    metadata={
        'scope': '通用',
        'guard_rule': '空闲或活动中',
        'help': {
            'category': '系统',
            'summary': '用一个兑换码换回数据里写好的发放',
            'usage': ('兑换 XN2026', '兑换 <码>',),
            'side_effect': '每个码每人限次（数据里定）；码是 3–32 位大写字母数字，不区分大小写，允许首尾空白',
            'order': 80,
        },
    },
)
async def redeem_code(
    user_id: str, message: str, message_context: MessageContext, manager: Any
) -> None:
    feature = current_game_services().features.duihuan
    raw = ' '.join(str(message or '').split())
    try:
        await manager.send(
            reply.result(
                feature, await feature.redeem(user_id, message_context.request_id, raw)
            )
        )
    except (DuihuanError, DuihuanConflictError) as exc:
        await manager.send(reply.error(feature, str(exc), feature.format_actions()))


__all__ = []
