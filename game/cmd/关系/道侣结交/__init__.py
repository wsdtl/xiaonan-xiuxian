"""道侣交谈、赠礼、邀约和暂别命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.daolv_jiejiao import (
    CompanionFarewellRequest,
    CompanionGiftRequest,
    CompanionInteractionError,
    CompanionInvitationRequest,
)

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="交谈",
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "关系",
            "summary": "与身边的世界道侣交谈",
            "usage": ("交谈 苏药尘", "交谈 名称", "交谈 编号或名称"),
            "side_effect": "只读交谈，不增加好感",
            "order": 20,
        },
    },
)
async def converse_companion(user_id: str, message: str, manager: Any) -> None:
    services = current_game_services()
    feature = services.features.daolv_jiejiao
    copy = feature.copy()
    try:
        result = await feature.converse_from_text(user_id, message)
        actions = feature.actions("交谈", result.view)
        await send_game_reply(
            reply.conversation(copy, result, actions),
            title=f"交谈 {result.view.name}",
        )
    except CompanionInteractionError as exc:
        await send_game_reply(
            reply.error(copy, str(exc), feature.format_actions("格式交谈")),
            title="交谈",
        )


@GameCommand.command(
    cmd="赠予",
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "关系",
            "summary": "向身边道侣赠送其喜欢的灵植",
            "usage": (
                "赠予 道侣 黄品云参 3",
                "赠予 道侣 <品级><灵植> [数量]",
            ),
            "side_effect": "消耗灵植并增加好感，首次圆满时发放一次回礼",
            "order": 30,
        },
    },
)
async def gift_companion(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    services = current_game_services()
    feature = services.features.daolv_jiejiao
    copy = feature.copy()
    try:
        result = await feature.gift_from_text(
            user_id, message_context.request_id, message
        )
        actions = feature.actions("赠礼", result.view)
        await send_game_reply(
            reply.gift(copy, result, actions),
            title=f"赠予 {result.view.name} {result.item.name}",
        )
    except (CompanionInteractionError, ValueError) as exc:
        await send_game_reply(
            reply.error(copy, str(exc), feature.format_actions("格式赠予")),
            title="赠予",
        )


@GameCommand.command(
    cmd="邀约",
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "关系",
            "summary": "邀约好感圆满的道侣同行",
            "usage": ("邀约 苏药尘", "邀约 名称", "邀约 编号或名称"),
            "side_effect": "占用唯一同行道侣位，首次邀约会固定个人资质与实力波动",
            "order": 40,
        },
    },
)
async def invite_companion(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    services = current_game_services()
    feature = services.features.daolv_jiejiao
    copy = feature.copy()
    try:
        result = await feature.invite_from_text(
            user_id, message_context.request_id, message
        )
        actions = feature.actions("邀约", result.view)
        await send_game_reply(
            reply.invitation(copy, result, actions),
            title=f"邀约 {result.view.name}",
        )
    except (CompanionInteractionError, ValueError) as exc:
        await send_game_reply(
            reply.error(copy, str(exc), feature.format_actions("格式邀约")),
            title="邀约",
        )


@GameCommand.command(
    cmd="暂别",
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "关系",
            "summary": "让当前同行道侣返回其原本所在地",
            "usage": ("暂别 苏药尘", "暂别 名称", "暂别 编号或名称"),
            "side_effect": "清除同行位，保留好感、赠礼历史与个人实例",
            "order": 50,
        },
    },
)
async def farewell_companion(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    services = current_game_services()
    feature = services.features.daolv_jiejiao
    copy = feature.copy()
    try:
        result = await feature.farewell_from_text(
            user_id, message_context.request_id, message
        )
        actions = feature.farewell_actions(result.definition.companion_id)
        await send_game_reply(
            reply.farewell(copy, result, actions),
            title=f"暂别 {result.definition.name}",
        )
    except (CompanionInteractionError, ValueError) as exc:
        await send_game_reply(
            reply.error(copy, str(exc), feature.format_actions("格式暂别")),
            title="暂别",
        )


__all__ = []
