"""快捷查看：只取一件事的摘要，不拉全表。"""

from __future__ import annotations

from game.app import current_game_services

from ...command import GameCommand
from . import reply
from typing import Any


@GameCommand.fullmatch(
    cmd="灵石",
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "资源",
            "summary": "只看灵石：合计折算与各品级数量",
            "usage": ("灵石",),
            "side_effect": "只读查询，不消耗或改变任何资产",
            "order": 6,
        },
    },
)
async def show_spirit_stone(user_id: str, message_context: Any, manager: Any) -> None:
    feature = current_game_services().features.najie
    view = await feature.spirit_stone(user_id)
    await manager.send(reply.spirit_stone(feature.copy_spirit_stone(), view))


@GameCommand.fullmatch(
    cmd="状态",
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "角色",
            "summary": "只看现在在干什么：位置、空间与状态标签",
            "usage": ("状态",),
            "side_effect": "只读查询，不改变任何状态",
            "order": 7,
        },
    },
)
async def show_status(user_id: str, message_context: Any, manager: Any) -> None:
    feature = current_game_services().features.weizhi
    view = await feature.status_summary(user_id)
    await manager.send(reply.status(feature.status_copy(), view))
