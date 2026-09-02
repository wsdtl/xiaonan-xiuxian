"""玩家宗门关系命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.zongmen import SectFeatureError

from ...command import GameCommand
from . import reply


@GameCommand.command(
    cmd="宗门",
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "创建和管理玩家宗门",
            "usage": (
                "宗门",
                "宗门 创建 宗门名",
                "宗门 邀请 角色名或编号",
                "宗门 接受",
                "宗门 拒绝",
                "宗门 退出",
                "宗门 逐出 角色名或编号",
                "宗门 任命长老 角色名或编号",
                "宗门 罢免长老 角色名或编号",
                "宗门 转让 角色名或编号",
                "宗门 解散",
            ),
            "side_effect": "宗门入口取当前地表坐标；建筑、仓库另行开放",
            "order": 36,
        },
    },
)
async def sect_command(*, user_id: str, message: str, message_context, manager) -> None:
    feature = current_game_services().features.zongmen
    parts = str(message or "").strip().split(maxsplit=2)
    try:
        if not parts:
            value = await feature.page(user_id)
            await manager.send(
                reply.page(feature.copy(), value, feature.page_actions(value.page))
            )
            return
        action = parts[0]
        target = parts[1].strip() if len(parts) >= 2 else ""
        extra = parts[2].strip() if len(parts) == 3 else ""
        request_id = message_context.request_id
        if action == "创建" and target and not extra:
            result = await feature.create(user_id, request_id, target)
        elif action == "邀请" and target and not extra:
            result = await feature.invite(user_id, target, request_id)
        elif action == "接受" and not target:
            result = await feature.accept(user_id, request_id)
        elif action == "拒绝" and not target:
            result = await feature.reject(user_id, request_id)
        elif action == "退出" and not target:
            result = await feature.leave(user_id, request_id)
        elif action == "逐出" and target and not extra:
            result = await feature.kick(user_id, target, request_id)
        elif action == "任命长老" and target and not extra:
            result = await feature.appoint_elder(user_id, target, request_id)
        elif action == "罢免长老" and target and not extra:
            result = await feature.remove_elder(user_id, target, request_id)
        elif action == "转让" and target and not extra:
            result = await feature.transfer(user_id, target, request_id)
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
    except SectFeatureError as exc:
        await manager.send(reply.error(feature.copy(), exc.code))


__all__ = []
