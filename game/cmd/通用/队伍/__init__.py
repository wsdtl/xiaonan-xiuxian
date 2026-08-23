"""玩家队伍命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.duiwu import TeamFeatureError

from ...command import GameCommand, HelpSpec
from . import reply


@GameCommand.command(
    scope="通用",
    cmd="队伍",
    aliases=("组队",),
    guard_rule="已创建",
    help=HelpSpec(
        category="行动",
        summary="查看和管理玩家队伍",
        usage=(
            "队伍",
            "队伍 邀请 角色名或user_id",
            "队伍 接受",
            "队伍 拒绝",
            "队伍 离开",
            "队伍 请离 角色名或user_id",
            "队伍 移交 角色名或user_id",
            "队伍 解散",
        ),
        side_effect="队伍成员将由队长带领行路和探险",
        order=35,
    ),
)
async def team_command(
    *,
    user_id: str,
    message: str,
    message_context,
    manager,
) -> None:
    feature = current_game_services().features.duiwu
    parts = str(message or "").strip().split(maxsplit=1)
    try:
        if not parts:
            value = await feature.page(user_id)
            await manager.send(
                reply.page(feature.copy(), value, feature.page_actions(value.page))
            )
            return
        action = parts[0]
        target = parts[1].strip() if len(parts) == 2 else ""
        request_id = message_context.request_id
        if action == "邀请":
            result = await feature.invite(user_id, target, request_id)
        elif action == "接受" and not target:
            result = await feature.accept(user_id, request_id)
        elif action == "拒绝" and not target:
            result = await feature.reject(user_id, request_id)
        elif action == "离开" and not target:
            result = await feature.leave(user_id, request_id)
        elif action == "请离":
            result = await feature.kick(user_id, target, request_id)
        elif action == "移交":
            result = await feature.transfer(user_id, target, request_id)
        elif action == "解散" and not target:
            result = await feature.disband(user_id, request_id)
        else:
            await manager.send(reply.format_error(feature.copy()))
            return
        await manager.send(
            reply.operation(
                feature.copy(),
                result,
                feature.page_actions(result.page.page),
            )
        )
    except TeamFeatureError as exc:
        await manager.send(reply.error(feature.copy(), exc.code))


__all__ = []
