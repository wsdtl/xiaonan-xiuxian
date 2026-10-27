"""人物与当前同行道侣的自动用药开关命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.fudan import (
    AutoMedicineRequest,
    MedicineFeatureConflictError,
    MedicineFeatureError,
)

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


async def _setting(
    target: str, *, user_id: str, message: str, message_context: MessageContext, manager: Any
) -> None:
    feature = current_game_services().features.fudan
    value = message.strip()
    if value not in {"开", "关"}:
        await send_game_reply(reply.error(feature, feature.copy("错误", "自动用药"), feature.format_actions()))
        return
    try:
        result = await feature.set_automatic(
            AutoMedicineRequest(
                user_id,
                message_context.request_id,
                target,
                value == "开",
            )
        )
        await send_game_reply(reply.setting(feature, result))
    except (MedicineFeatureError, MedicineFeatureConflictError) as exc:
        await send_game_reply(reply.error(feature, str(exc), feature.format_actions()))


@GameCommand.command(
    cmd=("人药", "人物自动用药"),
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "修行",
            "summary": "单独设置人物的战斗自动用药开关",
            "usage": ("人物自动用药 开", "人物自动用药 开或关",),
            "side_effect": "只改变人物开关，不影响道侣",
            "order": 100,
        },
    },
)
async def set_character_automatic(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    await _setting(
        "人物",
        user_id=user_id,
        message=message,
        message_context=message_context,
        manager=manager,
    )


@GameCommand.command(
    cmd=("侣药", "道侣自动用药"),
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "修行",
            "summary": "单独设置当前同行道侣的战斗自动用药开关",
            "usage": ("道侣自动用药 开", "道侣自动用药 开或关",),
            "side_effect": "只改变当前同行道侣开关，不影响人物",
            "order": 110,
        },
    },
)
async def set_companion_automatic(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    await _setting(
        "道侣",
        user_id=user_id,
        message=message,
        message_context=message_context,
        manager=manager,
    )


__all__ = []
