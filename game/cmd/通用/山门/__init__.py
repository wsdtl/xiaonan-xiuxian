"""宗门山门进出命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.zongmen_shanmen import GateFeatureError

from ...command import GameCommand
from . import reply


@GameCommand.fullmatch(
    cmd="入山门",
    metadata={
        "scope": "通用",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "行动",
            "summary": "进入当前宗门的独立洞天",
            "usage": ("入山门",),
            "side_effect": "领队带领当前同行成员一同进入宗门洞天",
            "order": 44,
        },
    },
)
async def enter_gate(*, user_id: str, message_context, manager) -> None:
    feature = current_game_services().features.zongmen_shanmen
    try:
        result = await feature.enter(user_id, message_context.request_id)
        await manager.send(reply.result(feature.copy(), result))
    except GateFeatureError as exc:
        await manager.send(reply.error(feature.copy(), exc.code))


@GameCommand.fullmatch(
    cmd="出山门",
    metadata={
        "scope": "通用",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "行动",
            "summary": "离开宗门洞天返回山门入口",
            "usage": ("出山门",),
            "side_effect": "领队带领当前同行成员一同返回山门入口",
            "order": 45,
        },
    },
)
async def leave_gate(*, user_id: str, message_context, manager) -> None:
    feature = current_game_services().features.zongmen_shanmen
    try:
        result = await feature.leave(user_id, message_context.request_id)
        await manager.send(reply.result(feature.copy(), result))
    except GateFeatureError as exc:
        await manager.send(reply.error(feature.copy(), exc.code))


__all__ = []
