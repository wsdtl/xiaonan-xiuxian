"""人物与当前同行道侣服丹命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.presentation import ItemRefError, parse_item_ref
from game.features.fudan import (
    AutoMedicineRequest,
    MedicineFeatureConflictError,
    MedicineFeatureError,
    MedicineUseRequest,
)

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


async def _use(
    target: str, *, user_id: str, message: str, message_context: MessageContext, manager: Any
) -> None:
    feature = current_game_services().features.fudan
    parts = message.rsplit(maxsplit=1)
    if not parts or len(parts) > 2:
        await send_game_reply(reply.error(feature, feature.copy("错误", "写法"), feature.format_actions()))
        return
    medicine = parts[0]
    grade = parts[1] if len(parts) == 2 else ""
    if len(parts) == 1:
        # 新写法：<品级><丹药>；拆不出品级就按原名交给玩法层（与从前一致）。
        try:
            ref = parse_item_ref(medicine)
            medicine, grade = ref.item, ref.grade
        except ItemRefError:
            pass
    try:
        result = await feature.use(
            MedicineUseRequest(
                user_id,
                message_context.request_id,
                target,
                medicine,
                grade,
            )
        )
        await send_game_reply(reply.used(feature, result))
    except (MedicineFeatureError, MedicineFeatureConflictError) as exc:
        await send_game_reply(reply.error(feature, str(exc), feature.format_actions()))


@GameCommand.command(
    cmd="人物服丹",
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "修行",
            "summary": "为人物服用恢复丹或寄存一枚战丹",
            "usage": ("人物服丹 小还丹", "人物服丹 玄品小还丹",),
            "side_effect": "消耗共享纳戒中的一枚丹药；每人最多寄存 1 枚战丹（已有待战战丹会被拒），恢复丹在资源已满时拒绝服用",
            "order": 80,
        },
    },
)
async def use_for_character(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    await _use(
        "人物",
        user_id=user_id,
        message=message,
        message_context=message_context,
        manager=manager,
    )


@GameCommand.command(
    cmd="道侣服丹",
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "修行",
            "summary": "为当前同行道侣服用恢复丹或寄存一枚战丹",
            "usage": ("道侣服丹 小还丹", "道侣服丹 玄品小还丹",),
            "side_effect": "消耗共享纳戒中的一枚丹药；每人最多寄存 1 枚战丹（已有待战战丹会被拒），恢复丹在资源已满时拒绝服用",
            "order": 90,
        },
    },
)
async def use_for_companion(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    await _use(
        "道侣",
        user_id=user_id,
        message=message,
        message_context=message_context,
        manager=manager,
    )


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
            "category": "系统",
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
            "category": "系统",
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
