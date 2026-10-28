"""战报通用命令：查看我的最近未过期战报（页面仍由 .site 提供 router）。"""

from __future__ import annotations

from typing import Any

from game.app import current_game_services

from ...command import GameCommand
from . import reply
from .site import router
from ...reply_composer import send_game_reply


@GameCommand.command(
    cmd="战报",
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "战斗",
            "summary": "查看个人、组队、宗门组队战报，每类最多 5 份",
            "usage": ("战报",),
            "side_effect": "只查看，不会改变任何状态",
            "order": 10,
        },
    },
)
async def show_my_reports_page(user_id: str, manager: Any) -> None:
    feature = current_game_services().features.zhanbao
    await send_game_reply(
        reply.view(feature, await feature.my_report_sections(user_id))
    )


__all__ = ["router"]
