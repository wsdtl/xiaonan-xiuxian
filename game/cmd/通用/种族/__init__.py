"""种族图鉴二级组件命令。"""

from __future__ import annotations

from game.app import current_game_services
from launch.paths import public_url

from ...command import GameCommand
from . import reply
from typing import Any


@GameCommand.command(
    cmd="种族",
    metadata={
        "scope": "通用",
        "guard_rule": "始终可用",
        "help": {
            "category": "角色",
            "summary": "查看全部种族：按族系分页，也可按编号或名字看某一个",
            "usage": ("种族", "种族 页码", "种族 编号", "种族 名字"),
            "side_effect": "只读查询，不改变人物、战斗或世界状态",
            "order": 20,
        },
    },
)
async def browse_races(user_id: str, message: str, manager: Any) -> None:
    query = " ".join(str(message or "").split())
    feature = current_game_services().features.zhongzu
    copy = feature.copy()
    if not query:
        await manager.send(reply.page(copy, feature.overview(), 1))
        return
    if query.isdigit() and len(query) <= 2:
        overview = feature.overview()
        index = int(query)
        if not 1 <= index <= len(overview.lineages):
            await manager.send(reply.invalid_page(copy, overview))
            return
        await manager.send(reply.page(copy, overview, index))
        return
    race = feature.find(query)
    if race is None:
        await manager.send(reply.missing(copy, query))
        return
    await manager.send(reply.detail(copy, race, public_url("baike")))


__all__ = []
