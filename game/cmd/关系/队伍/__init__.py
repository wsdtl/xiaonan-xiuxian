"""玩家队伍命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.duiwu import TeamFeatureError

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd=("队伍", "组队"),
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "关系",
            "summary": "查看和管理玩家队伍",
            "usage": (
                "队伍",
                "队伍 邀请 角色名或编号",
                "队伍 接受",
                "队伍 拒绝",
                "队伍 离开",
                "队伍 请离 角色名或编号",
                "队伍 移交 角色名或编号",
                "队伍 解散",
            ),
            "side_effect": "队伍成员将由队长带领行路和探险；队伍上限 3 人，邀请 600 秒内有效、对象须在附近且空闲，接受邀请须与邀请者同处",
            "order": 35,
        },
    },
)
async def team_command(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.duiwu
    try:
        entry = await feature.enter(
            user_id, message_context.request_id, message
        )
    except TeamFeatureError as exc:
        await send_game_reply(
            reply.error(feature.copy(), exc.code), title="队伍"
        )
        return
    if entry.kind == "format":
        await send_game_reply(
            reply.format_error(feature.copy(), feature.page_actions("格式")),
            title="队伍",
        )
    elif entry.kind == "page" and entry.page is not None:
        await send_game_reply(
            reply.page(
                feature.copy(), entry.page, feature.page_actions(entry.page)
            ),
            title="队伍",
        )
    elif entry.kind == "operation" and entry.operation is not None:
        operation = entry.operation
        title = f"队伍 {operation.action}"
        if operation.target_name:
            title += f" {operation.target_name}"
        await send_game_reply(
            reply.operation(
                feature.copy(),
                operation,
                feature.page_actions(operation.page),
            ),
            title=title,
        )


__all__ = []
