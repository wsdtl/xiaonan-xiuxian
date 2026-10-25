"""血脉命令（主命令「血脉」，子命令写在参数里）。"""

from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.xuemai import GenealogyQueryError, XuemaiError

from ...command import GameCommand
from . import input as command_input, reply

_SUBCOMMANDS = ("族谱",)


@GameCommand.command(
    cmd=("血脉", "血脉族谱"),
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "角色",
            "summary": "查看自己的族谱（只增不改，可作取名参考）",
            "usage": ("血脉 族谱", "血脉 族谱 名字或编号"),
            "side_effect": "只读族谱，不改动任何记录",
            "order": 30,
        },
    },
)
async def xuemai(user_id: str, message: str, manager: Any) -> None:
    services = current_game_services()
    feature = services.features.xuemai
    copy = feature.copy()
    param = command_input.parse(message)
    if param.subcommand not in _SUBCOMMANDS:
        await manager.send(reply.error(copy, "血脉的用法：血脉 族谱"))
        return
    try:
        view = await feature.genealogy(user_id, param.query)
        await manager.send(reply.genealogy(copy, view))
    except (GenealogyQueryError, XuemaiError) as exc:
        await manager.send(reply.error(copy, str(exc)))

@GameCommand.command(
    cmd=("传位",),
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "角色",
            "summary": "把这一壳传位给一个新生儿，结束这一代，开始下一代",
            "usage": ("传位 新生儿编号", "传位 新生儿名字"),
            "side_effect": "旧壳记入族谱并标已传位；境界等级属性构筑纳戒都不变，血脉按新生儿 DNA 重算",
            "order": 31,
        },
    },
)
async def succession(user_id: str, message: str, manager: Any) -> None:
    services = current_game_services()
    feature = services.features.xuemai
    copy = feature.copy()
    child = str(message or "").strip()
    if not child:
        await manager.send(reply.succession_usage(copy))
        return
    try:
        result = await feature.succession(user_id, child)
        await manager.send(reply.succession(copy, result))
    except (GenealogyQueryError, XuemaiError) as exc:
        await manager.send(reply.error(copy, str(exc)))