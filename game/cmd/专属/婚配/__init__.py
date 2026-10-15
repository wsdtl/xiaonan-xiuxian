"""生育命令。"""

from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.hunpei import HunpeiError

from ...command import GameCommand
from . import input as command_input, reply


@GameCommand.command(
    cmd="生育",
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "道侣",
            "summary": "与当前同行道侣生育，生成下一代",
            "usage": ("生育",),
            "side_effect": "消耗生育丹并记本代胎次；新生儿入族谱，血脉按新生儿 DNA 匹配",
            "order": 25,
        },
    },
)
async def birth(user_id: str, message: str, manager: Any) -> None:
    services = current_game_services()
    feature = services.features.hunpei
    copy = feature.copy()
    command_input.parse(message)
    try:
        state = await feature.view(user_id)
        if not state.can_birth:
            await manager.send(reply.birth(copy, state))
            return
        result = await feature.birth(user_id)
        await manager.send(reply.born(copy, result))
    except HunpeiError as exc:
        await manager.send(reply.error(copy, str(exc)))
