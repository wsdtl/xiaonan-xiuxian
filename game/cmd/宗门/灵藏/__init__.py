"""宗门洞天专属灵藏命令。"""
from __future__ import annotations

from game.app import current_game_services
from game.features.presentation import ItemRefError
from game.features.zongmen_lingcang import LingcangFeatureError

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any

@GameCommand.command(
    cmd="灵藏",
    metadata={
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "宗门",
            "summary": "在宗门园区灵藏查看宗门基础资源，或向本宗捐入材料",
            "usage": (
                "灵藏",
                "灵藏 灵植",
                "灵藏 灵矿 2",
                "灵藏 捐入 灵石 100",
                "灵藏 捐入 灵植 黄品云参 3",
            ),
            "side_effect": "只读查看；捐入扣个人资源、计入宗门灵藏，取用只发生在炼制与产出结算",
            "order": 80,
        },
    },
)
async def lingcang(
    user_id: str, message: str, message_context: MessageContext, manager: Any
) -> None:
    feature = current_game_services().features.zongmen_lingcang
    try:
        entry = await feature.enter(
            user_id, message_context.request_id, message
        )
    except (LingcangFeatureError, ItemRefError) as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc)))
        return
    if entry.kind == "page" and entry.page is not None:
        await send_game_reply(
            reply.page(
                feature.copy(), entry.page, feature.page_actions(entry.page)
            )
        )
    elif entry.kind == "donated_stones" and entry.transfer is not None:
        await send_game_reply(
            reply.donated_stones(
                feature.copy(), entry.quantity, entry.transfer
            )
        )
    elif entry.kind == "donated_material" and entry.transfer is not None:
        await send_game_reply(
            reply.donated_material(feature.copy(), entry.transfer)
        )


__all__ = []
