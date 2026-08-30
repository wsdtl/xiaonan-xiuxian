"""玩家帮助二级组件。"""

from __future__ import annotations

from ...command import GameCommand, HelpSpec
from . import reply


@GameCommand.command(
    scope="通用",
    cmd="帮助",
    guard_rule="始终可用",
    help=HelpSpec(
        category="角色",
        summary="查看当前已经开放的命令分类、用法和结果",
        usage=("帮助", "帮助 分类", "帮助 命令"),
        order=0,
    ),
)
async def help_command(*, message: str, manager) -> None:
    await manager.send(reply.help_message(message))


__all__ = []
