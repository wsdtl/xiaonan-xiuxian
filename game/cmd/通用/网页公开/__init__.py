from __future__ import annotations

from game.app import current_game_services
from game.features.wangye import WangyeConflictError, WangyeError

from ...command import GameCommand
from . import reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.fullmatch(
    cmd=('网页公开', '网页资源公开'),
    metadata={
        'scope': '通用',
        'guard_rule': '已创建',
        'help': {
            'category': '系统',
            'summary': '打开网页读取开关：网页可以直接读你的数据，你也能在这些网页里挑自己',
            'usage': ('网页资源公开', '网页公开'),
            'side_effect': '只改一个开关，不动任何资产',
            'order': 82,
        },
    },
)
async def web_public_on(user_id: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.wangye
    try:
        await feature.set_public(user_id, message_context.request_id, True)
        await manager.send(reply.notice(feature, True))
    except (WangyeError, WangyeConflictError) as exc:
        await manager.send(reply.error(feature, str(exc)))


@GameCommand.fullmatch(
    cmd=('网页关闭', '网页资源关闭'),
    metadata={
        'scope': '通用',
        'guard_rule': '已创建',
        'help': {
            'category': '系统',
            'summary': '关闭网页读取开关：网页不再读你的数据，这些页面里也不会有你',
            'usage': ('网页资源关闭', '网页关闭'),
            'side_effect': '只改一个开关，不动任何资产',
            'order': 83,
        },
    },
)
async def web_public_off(user_id: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.wangye
    try:
        await feature.set_public(user_id, message_context.request_id, False)
        await manager.send(reply.notice(feature, False))
    except (WangyeError, WangyeConflictError) as exc:
        await manager.send(reply.error(feature, str(exc)))


__all__ = []
