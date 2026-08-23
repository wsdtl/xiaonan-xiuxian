"""道侣查看、交谈、赠礼、邀约和暂别命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.daolv_jiejiao import (
    CompanionFarewellRequest,
    CompanionGiftRequest,
    CompanionInteractionError,
    CompanionInvitationRequest,
)

from ...command import GameCommand, HelpSpec
from . import input as command_input
from . import reply


@GameCommand.command(
    scope="专属",
    cmd="查看道侣",
    aliases=("道侣查看",),
    guard_rule="自主空闲或休息",
    help=HelpSpec(
        category="道侣",
        summary="查看身边道侣的身份、性情、喜好与当前关系",
        usage=("查看道侣 名称", "查看道侣 编号"),
        side_effect="只读查询，不改变关系或物品",
        order=10,
    ),
)
async def inspect_companion(*, user_id: str, message: str, manager, **_) -> None:
    services = current_game_services()
    feature = services.features.daolv_jiejiao
    copy = feature.copy()
    query = str(message or "").strip()
    if not query:
        await manager.send(reply.error(copy, reply.text(copy, "命令", "查看格式")))
        return
    try:
        view = await feature.inspect(user_id, query)
        actions = await _with_location_actions(
            services,
            user_id,
            feature.actions("查看", view),
        )
        await manager.send(reply.view(copy, view, actions))
    except CompanionInteractionError as exc:
        await manager.send(reply.error(copy, str(exc)))


@GameCommand.command(
    scope="专属",
    cmd="交谈",
    aliases=("道侣交谈",),
    guard_rule="自主空闲或休息",
    help=HelpSpec(
        category="道侣",
        summary="与身边的世界道侣交谈",
        usage=("交谈 名称", "交谈 编号"),
        side_effect="只读交谈，不增加好感",
        order=20,
    ),
)
async def converse_companion(*, user_id: str, message: str, manager, **_) -> None:
    services = current_game_services()
    feature = services.features.daolv_jiejiao
    copy = feature.copy()
    query = str(message or "").strip()
    if not query:
        await manager.send(reply.error(copy, reply.text(copy, "命令", "交谈格式")))
        return
    try:
        result = await feature.converse(user_id, query)
        actions = await _with_location_actions(
            services,
            user_id,
            feature.actions("交谈", result.view),
        )
        await manager.send(reply.conversation(copy, result, actions))
    except CompanionInteractionError as exc:
        await manager.send(reply.error(copy, str(exc)))


@GameCommand.command(
    scope="专属",
    cmd="赠予",
    guard_rule="自主空闲或休息",
    help=HelpSpec(
        category="道侣",
        summary="向身边道侣赠送其喜欢的灵植",
        usage=("赠予 道侣 灵植", "赠予 道侣 灵植 数量", "赠予 道侣 灵植 品级 数量"),
        side_effect="消耗灵植并增加好感，首次圆满时发放一次回礼",
        order=30,
    ),
)
async def gift_companion(
    *, user_id: str, message: str, message_context, manager
) -> None:
    services = current_game_services()
    feature = services.features.daolv_jiejiao
    copy = feature.copy()
    try:
        companion, item, grade, quantity = command_input.gift_arguments(message)
        result = await feature.gift(
            CompanionGiftRequest(
                user_id, message_context.request_id, companion, item, grade, quantity
            )
        )
        actions = await _with_location_actions(
            services,
            user_id,
            feature.actions("赠礼", result.view),
        )
        await manager.send(reply.gift(copy, result, actions))
    except (CompanionInteractionError, ValueError) as exc:
        await manager.send(reply.error(copy, str(exc)))


@GameCommand.command(
    scope="专属",
    cmd="邀约",
    aliases=("邀约道侣",),
    guard_rule="自主空闲或休息",
    help=HelpSpec(
        category="道侣",
        summary="邀约好感圆满的道侣同行",
        usage=("邀约 名称", "邀约 编号"),
        side_effect="占用唯一同行道侣位，首次邀约会固定个人资质与实力波动",
        order=40,
    ),
)
async def invite_companion(
    *, user_id: str, message: str, message_context, manager
) -> None:
    services = current_game_services()
    feature = services.features.daolv_jiejiao
    copy = feature.copy()
    query = str(message or "").strip()
    if not query:
        await manager.send(reply.error(copy, reply.text(copy, "命令", "邀约格式")))
        return
    try:
        result = await feature.invite(
            CompanionInvitationRequest(user_id, message_context.request_id, query)
        )
        actions = await _with_location_actions(
            services,
            user_id,
            feature.actions("邀约", result.view),
        )
        await manager.send(reply.invitation(copy, result, actions))
    except (CompanionInteractionError, ValueError) as exc:
        await manager.send(reply.error(copy, str(exc)))


@GameCommand.command(
    scope="专属",
    cmd="暂别",
    aliases=("暂别道侣",),
    guard_rule="自主空闲或休息",
    help=HelpSpec(
        category="道侣",
        summary="让当前同行道侣返回其原本所在地",
        usage=("暂别 名称", "暂别 编号"),
        side_effect="清除同行位，保留好感、赠礼历史与个人实例",
        order=50,
    ),
)
async def farewell_companion(
    *, user_id: str, message: str, message_context, manager
) -> None:
    services = current_game_services()
    feature = services.features.daolv_jiejiao
    copy = feature.copy()
    query = str(message or "").strip()
    if not query:
        await manager.send(reply.error(copy, reply.text(copy, "命令", "暂别格式")))
        return
    try:
        result = await feature.farewell(
            CompanionFarewellRequest(user_id, message_context.request_id, query)
        )
        actions = await _with_location_actions(
            services,
            user_id,
            feature.farewell_actions(result.definition.companion_id),
        )
        await manager.send(reply.farewell(copy, result, actions))
    except (CompanionInteractionError, ValueError) as exc:
        await manager.send(reply.error(copy, str(exc)))


async def _with_location_actions(services, user_id: str, business_actions: tuple):
    location_actions = await services.features.weizhi.current_location_actions(user_id)
    return business_actions + location_actions


__all__ = []
