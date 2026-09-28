"""纳戒分类与分页入口。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.najie import NajieQueryError, NajieStateError

from ...command import GameCommand
from . import reply
from typing import Any


@GameCommand.command(
    cmd="纳戒",
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "资源",
            "summary": "分类查看物品、功法道藏、修行资粮、器藏、阵藏与所学",
            "usage": ("纳戒", "纳戒 大类", "纳戒 大类 小类", "纳戒 大类 小类 页码"),
            "side_effect": "只读查询，不消耗、装配或改变任何玩家资产",
            "order": 5,
        },
    },
)
async def show_najie(user_id: str, message: str, manager: Any) -> None:
    query = tuple(str(message or "").split())
    feature = current_game_services().features.najie
    try:
        if not query:
            message_value = reply.home(await feature.home(user_id))
        elif len(query) == 1:
            message_value = reply.category(await feature.category(user_id, query[0]))
        elif len(query) in {2, 3}:
            page = _page_number(query[2]) if len(query) == 3 else 1
            message_value = reply.page(
                await feature.page(user_id, query[0], query[1], page)
            )
        else:
            raise NajieQueryError("纳戒命令最多接收大类、小类和页码")
    except (NajieQueryError, NajieStateError) as exc:
        message_value = reply.error(str(exc))
    await manager.send(message_value)


def _page_number(value: str) -> int:
    if not value.isdecimal() or int(value) < 1:
        raise NajieQueryError("纳戒页码必须是正整数")
    return int(value)


__all__ = []
