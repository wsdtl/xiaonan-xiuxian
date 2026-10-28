"""血脉命令（主命令「血脉」，子命令写在参数里）。"""

from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.xuemai import GenealogyQueryError, XuemaiError

from ...command import GameCommand
from . import input as command_input, reply
from ...reply_composer import send_game_reply

_SUBCOMMANDS = ("族谱",)


@GameCommand.command(
    cmd="血脉",
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "修行",
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
        await send_game_reply(
            reply.error(copy, "血脉的用法：血脉 族谱"), title="血脉"
        )
        return
    try:
        view = await feature.genealogy(user_id, param.query)
        await send_game_reply(reply.genealogy(copy, view), title="血脉 族谱")
    except (GenealogyQueryError, XuemaiError) as exc:
        await send_game_reply(reply.error(copy, str(exc)), title="血脉")

@GameCommand.command(
    cmd=("传位",),
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "修行",
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
        await send_game_reply(reply.succession_usage(copy), title="传位")
        return
    try:
        result = await feature.succession(user_id, child)
        await send_game_reply(
            reply.succession(copy, result),
            title=f"传位 {result.new_name}",
        )
    except (GenealogyQueryError, XuemaiError) as exc:
        await send_game_reply(reply.error(copy, str(exc)), title="传位")