"""玩家宗门关系命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.zongmen import SectFeatureError

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="宗门",
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "宗门",
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
            "side_effect": "宗门入口取当前地表坐标；邀请 600 秒内有效、对象须在附近且空闲，接受邀请须与邀请者同处；宗主不能退出（须先转让或解散），解散要求宗藏与万珍殿为空；建筑、仓库另行开放",
            "order": 36,
        },
    },
)
async def sect_command(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.zongmen
    try:
        entry = await feature.enter(
            user_id, message_context.request_id, message
        )
    except SectFeatureError as exc:
        await send_game_reply(reply.error(feature.copy(), exc.code), title="宗门")
        return
    if entry.kind == "format":
        await send_game_reply(
            reply.format_error(feature.copy(), feature.page_actions("格式")),
            title="宗门",
        )
    elif entry.kind == "page" and entry.page is not None:
        title = f"宗门 {entry.page.name}" if entry.page.name else "宗门"
        await send_game_reply(
            reply.page(
                feature.copy(), entry.page, feature.page_actions(entry.page.page)
            ),
            title=title,
        )
    elif entry.kind == "operation" and entry.operation is not None:
        operation = entry.operation
        title = f"宗门 {operation.action}"
        if operation.target_name:
            title += f" {operation.target_name}"
        await send_game_reply(
            reply.operation(
                feature.copy(),
                operation,
                feature.page_actions(operation.page.page),
            ),
            title=title,
        )


__all__ = []
