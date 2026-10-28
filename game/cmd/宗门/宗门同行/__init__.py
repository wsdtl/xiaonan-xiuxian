"""宗门同行命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.zongmen_tongxing import SectFollowFeatureError

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="宗门同行",
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "宗门",
            "summary": "召集或加入本宗同行",
            "usage": (
                "宗门同行",
                "宗门同行 召集",
                "宗门同行 加入",
                "宗门同行 离开",
                "宗门同行 请离 角色名或编号",
                "宗门同行 解散",
            ),
            "side_effect": "同行成员随宗主共同去、探险、闭关、采药和采矿；加入要求宗主已召集、与宗主同处、本人不在队伍中，同行上限 15 人",
            "order": 36,
        },
    },
)
async def sect_follow_command(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.zongmen_tongxing
    try:
        entry = await feature.enter(
            user_id, message_context.request_id, message
        )
    except SectFollowFeatureError as exc:
        await send_game_reply(
            reply.error(feature.copy(), exc.code, feature.page_actions("格式")),
            title="宗门同行",
        )
        return
    if entry.kind == "format":
        await send_game_reply(
            reply.format_error(feature.copy(), feature.page_actions("格式")),
            title="宗门同行",
        )
    elif entry.kind == "page" and entry.page is not None:
        await send_game_reply(
            reply.page(
                feature.copy(), entry.page, feature.page_actions(entry.page.page)
            ),
            title="宗门同行",
        )
    elif entry.kind == "result" and entry.result is not None:
        result = entry.result
        title = f"宗门同行 {result.action}"
        if result.target_name:
            title += f" {result.target_name}"
        await send_game_reply(
            reply.operation(
                feature.copy(),
                result,
                feature.page_actions(result.page.page),
            ),
            title=title,
        )


__all__ = []
