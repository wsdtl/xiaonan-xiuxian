"""玩家托管命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.tuoguan import HostingFeatureError

from ...command import GameCommand, HelpSpec
from . import reply
from . import runtime as runtime


@GameCommand.command(
    scope="通用",
    cmd="托管",
    guard_rule="已创建",
    help=HelpSpec(
        category="行动",
        summary="查看托管状态或按自定义活动顺序托管当前同行",
        usage=("托管", "托管 探险 闭关", "托管 采药 采矿"),
        side_effect="队长或宗主统一托管当前同行；每项活动固定执行三十分钟",
        order=42,
    ),
)
async def hosting_command(
    *, user_id: str, message: str, message_context, manager
) -> None:
    feature = current_game_services().features.tuoguan
    try:
        activities = tuple(str(message or "").split())
        value = (
            await feature.start(user_id, message_context.request_id, activities)
            if activities
            else await feature.current(user_id)
        )
        if value.action == "开启" and value.session is not None:
            runtime.schedule_plan(value.session)
        await manager.send(reply.result(feature.copy(), value))
    except HostingFeatureError as exc:
        await manager.send(reply.error(feature.copy(), exc.code))


@GameCommand.fullmatch(
    scope="通用",
    cmd="继续托管",
    guard_rule="已创建",
    help=HelpSpec(
        category="行动",
        summary="由原队长或宗主恢复暂停的托管计划",
        usage=("继续托管",),
        side_effect="从暂停的当前步骤重新执行，不跳过失败活动",
        order=42,
    ),
)
async def resume_hosting(*, user_id: str, message_context, manager) -> None:
    feature = current_game_services().features.tuoguan
    try:
        value = await feature.resume(user_id, message_context.request_id)
        if value.session is not None:
            runtime.schedule_plan(value.session)
        await manager.send(reply.result(feature.copy(), value))
    except HostingFeatureError as exc:
        await manager.send(reply.error(feature.copy(), exc.code))


@GameCommand.fullmatch(
    scope="通用",
    cmd="取消托管",
    guard_rule="已创建",
    help=HelpSpec(
        category="行动",
        summary="结束本人或当前同行的托管",
        usage=("取消托管",),
        side_effect="单人恢复自主；领队会统一取消当前托管会话",
        order=43,
    ),
)
async def cancel_hosting(*, user_id: str, message_context, manager) -> None:
    feature = current_game_services().features.tuoguan
    try:
        value = await feature.cancel(user_id, message_context.request_id)
        if value.session is not None:
            runtime.cancel_plan(value.session.session_id)
        await manager.send(reply.result(feature.copy(), value))
    except HostingFeatureError as exc:
        await manager.send(reply.error(feature.copy(), exc.code))


__all__ = []
