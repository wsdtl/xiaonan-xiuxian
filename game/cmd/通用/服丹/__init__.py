"""人物与当前同行道侣服丹命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.fudan import (
    AutoMedicineRequest,
    MedicineFeatureConflictError,
    MedicineFeatureError,
    MedicineUseRequest,
)

from ...command import GameCommand, HelpSpec
from . import reply


async def _use(
    target: str, *, user_id: str, message: str, message_context, manager
) -> None:
    parts = message.rsplit(maxsplit=1)
    if not parts or len(parts) > 2:
        await manager.send(reply.error("格式不正确"))
        return
    medicine = parts[0]
    grade = parts[1] if len(parts) == 2 else ""
    feature = current_game_services().features.fudan
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
        await manager.send(reply.used(feature, result))
    except (MedicineFeatureError, MedicineFeatureConflictError) as exc:
        await manager.send(reply.error(str(exc)))


@GameCommand.command(
    scope="通用",
    cmd="人物服丹",
    guard_rule="已创建",
    help=HelpSpec(
        category="修行",
        summary="为人物服用恢复丹或寄存一枚战丹",
        usage=("人物服丹 丹药编号或名称 [品级]",),
        side_effect="消耗共享纳戒中的一枚丹药",
        order=80,
    ),
)
async def use_for_character(
    *, user_id: str, message: str, message_context, manager
) -> None:
    await _use(
        "人物",
        user_id=user_id,
        message=message,
        message_context=message_context,
        manager=manager,
    )


@GameCommand.command(
    scope="通用",
    cmd="道侣服丹",
    guard_rule="已创建",
    help=HelpSpec(
        category="修行",
        summary="为当前同行道侣服用恢复丹或寄存一枚战丹",
        usage=("道侣服丹 丹药编号或名称 [品级]",),
        side_effect="消耗共享纳戒中的一枚丹药",
        order=90,
    ),
)
async def use_for_companion(
    *, user_id: str, message: str, message_context, manager
) -> None:
    await _use(
        "道侣",
        user_id=user_id,
        message=message,
        message_context=message_context,
        manager=manager,
    )


async def _setting(
    target: str, *, user_id: str, message: str, message_context, manager
) -> None:
    value = message.strip()
    if value not in {"开", "关"}:
        await manager.send(reply.error("自动用药只能设置为开或关"))
        return
    feature = current_game_services().features.fudan
    try:
        result = await feature.set_automatic(
            AutoMedicineRequest(
                user_id,
                message_context.request_id,
                target,
                value == "开",
            )
        )
        await manager.send(reply.setting(feature, result))
    except (MedicineFeatureError, MedicineFeatureConflictError) as exc:
        await manager.send(reply.error(str(exc)))


@GameCommand.command(
    scope="通用",
    cmd="人药",
    aliases=("人物自动用药",),
    guard_rule="已创建",
    help=HelpSpec(
        category="修行",
        summary="单独设置人物的战斗自动用药开关",
        usage=("人物自动用药 开或关",),
        side_effect="只改变人物开关，不影响道侣",
        order=100,
    ),
)
async def set_character_automatic(
    *, user_id: str, message: str, message_context, manager
) -> None:
    await _setting(
        "人物",
        user_id=user_id,
        message=message,
        message_context=message_context,
        manager=manager,
    )


@GameCommand.command(
    scope="通用",
    cmd="侣药",
    aliases=("道侣自动用药",),
    guard_rule="已创建",
    help=HelpSpec(
        category="修行",
        summary="单独设置当前同行道侣的战斗自动用药开关",
        usage=("道侣自动用药 开或关",),
        side_effect="只改变当前同行道侣开关，不影响人物",
        order=110,
    ),
)
async def set_companion_automatic(
    *, user_id: str, message: str, message_context, manager
) -> None:
    await _setting(
        "道侣",
        user_id=user_id,
        message=message,
        message_context=message_context,
        manager=manager,
    )


__all__ = []
