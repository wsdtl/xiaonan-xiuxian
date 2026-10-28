"""纳戒分类与分页入口。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.najie import NajieQueryError, NajieStateError

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from typing import Any


@GameCommand.command(
    cmd="纳戒",
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "查看与工具",
            "summary": "分类查看物品、功法道藏、修行资粮、器藏、阵藏与所学",
            "usage": ("纳戒", "纳戒 大类", "纳戒 大类 小类", "纳戒 大类 小类 页码"),
            "side_effect": "只读查询，不消耗、装配或改变任何玩家资产",
            "order": 5,
        },
    },
)
async def show_najie(user_id: str, message: str, manager: Any) -> None:
    feature = current_game_services().features.najie
    try:
        entry = await feature.enter_query(user_id, message)
        if entry.kind == "home" and entry.home is not None:
            message_value = reply.home(entry.home)
        elif entry.kind == "category" and entry.category is not None:
            message_value = reply.category(entry.category)
        elif entry.kind == "page" and entry.page is not None:
            message_value = reply.page(entry.page)
        else:
            raise NajieQueryError("纳戒查询结果无效")
    except (NajieQueryError, NajieStateError) as exc:
        message_value = reply.error(str(exc))
    await send_game_reply(message_value)


__all__ = []
