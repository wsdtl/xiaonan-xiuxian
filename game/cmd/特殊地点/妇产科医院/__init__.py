"""生育与求子命令。"""
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
            "summary": "在妇产科医院与当前同行道侣生育，消耗生育丹生成下一代",
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


@GameCommand.command(
    cmd="求子",
    metadata={
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "道侣",
            "summary": "在妇产科医院向附近的异性玩家求子：一男一女、求方需生育丹、双方都必须在医院，孩子归求方",
            "usage": ("求子 玩家名", "求子 待办", "求子 同意 [编号]", "求子 拒绝 [编号]"),
            "side_effect": "同意时消耗求方的生育丹并按求方胎次计；双方都必须在妇产科医院；孩子只进求方族谱，被求者不留记录",
            "order": 26,
        },
    },
)
async def ask_child(user_id: str, message: str, manager: Any) -> None:
    services = current_game_services()
    feature = services.features.hunpei
    copy = feature.copy()
    command = command_input.parse_request(message)
    try:
        if command.action == "ask":
            asked = await feature.ask(user_id, command.argument)
            await manager.send(reply.asked(copy, asked))
            return
        if command.action == "agree":
            result = await feature.respond(user_id, command.argument, True)
            await manager.send(reply.responded(copy, result))
            return
        if command.action == "refuse":
            result = await feature.respond(user_id, command.argument, False)
            await manager.send(reply.responded(copy, result))
            return
        pending = await feature.pending(user_id)
        await manager.send(reply.pending(copy, pending))
    except HunpeiError as exc:
        await manager.send(reply.error(copy, str(exc)))
