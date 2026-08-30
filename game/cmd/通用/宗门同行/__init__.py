"""宗门同行命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.zongmen_tongxing import SectFollowFeatureError

from ...command import GameCommand, HelpSpec
from . import reply


@GameCommand.command(
    scope="通用",
    cmd="宗门同行",
    guard_rule="已创建",
    help=HelpSpec(
        category="行动",
        summary="召集或加入本宗同行",
        usage=(
            "宗门同行",
            "宗门同行 召集",
            "宗门同行 加入",
            "宗门同行 离开",
            "宗门同行 请离 角色名或编号",
            "宗门同行 解散",
        ),
        side_effect="同行成员随宗主共同去、探险、闭关、采药和采矿",
        order=36,
    ),
)
async def sect_follow_command(
    *, user_id: str, message: str, message_context, manager
) -> None:
    feature = current_game_services().features.zongmen_tongxing
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
        if action == "召集" and not target:
            result = await feature.assemble(user_id, request_id)
        elif action == "加入" and not target:
            result = await feature.join(user_id, request_id)
        elif action == "离开" and not target:
            result = await feature.leave(user_id, request_id)
        elif action == "请离" and target:
            result = await feature.kick(user_id, target, request_id)
        elif action == "解散" and not target:
            result = await feature.disband(user_id, request_id)
        else:
            await manager.send(reply.format_error(feature.copy()))
            return
        await manager.send(
            reply.operation(
                feature.copy(), result, feature.page_actions(result.page.page)
            )
        )
    except SectFollowFeatureError as exc:
        await manager.send(reply.error(feature.copy(), exc.code))


__all__ = []
