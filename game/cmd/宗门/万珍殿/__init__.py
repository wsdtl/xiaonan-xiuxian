"""宗门洞天专属万珍殿命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.presentation import ItemRefError
from game.features.zongmen_wanzhen import WanzhenFeatureError

from ...command import GameCommand
from . import reply
from .site import router
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any

@GameCommand.command(
    cmd="万珍殿",
    metadata={
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "宗门",
            "summary": "在本宗宗门园区查看万珍殿成品，或向本宗捐入、由执掌者发放成品",
            "usage": (
                "万珍殿",
                "万珍殿 丹药",
                "万珍殿 阵法 2",
                "万珍殿 捐入 丹药 01100005 3",
                "万珍殿 发放 角色名 01100005",
                "万珍殿 领取 阵法名",
            ),
            "side_effect": "查看只读；捐入扣个人成品、发放/领取扣宗门成品，均记入同一事务；发放与领取仅宗主/长老",
            "order": 82,
        },
    },
)
async def show_wanzhen(
    user_id: str, message: str, message_context: MessageContext, manager: Any
) -> None:
    feature = current_game_services().features.zongmen_wanzhen
    try:
        entry = await feature.enter(
            user_id, message_context.request_id, message
        )
    except (WanzhenFeatureError, ItemRefError) as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc)), title="万珍殿")
        return
    if entry.kind == "page" and entry.page is not None:
        await send_game_reply(
            reply.page(
                feature.copy(), entry.page, feature.page_actions(entry.page)
            ),
            title="万珍殿",
        )
    elif entry.kind == "transferred" and entry.transfer is not None:
        await send_game_reply(
            reply.transferred(feature.copy(), entry.transfer),
            title=f"万珍殿 {entry.transfer.entry.name}",
        )


__all__ = ["router"]
