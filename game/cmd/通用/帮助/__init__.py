"""玩家帮助二级组件。"""

from __future__ import annotations

# 多分支命令与帮助同类（都是命令导航）；显式导入才会注册。
from . import branches as _branches  # noqa: F401

from ...command import GameCommand
from . import reply
from typing import Any


@GameCommand.command(
    cmd="帮助",
    metadata={
        "scope": "通用",
        "guard_rule": "始终可用",
        "help": {
            "category": "角色",
            "summary": "查看当前已经开放的命令分类、用法和结果",
            "usage": ("帮助", "帮助 分类", "帮助 命令"),
            "order": 0,
        },
    },
)
async def help_command(message: str, manager: Any) -> None:
    await manager.send(reply.help_message(message))


@GameCommand.command(
    cmd="help",
    metadata={
        "scope": "通用",
        "guard_rule": "始终可用",
        # 刻意不写 help 块：这条命令不参与「帮助」的分类联动，也不出现在帮助页里。
        "hidden": True,
    },
)
async def id_help_command(message: str, manager: Any) -> None:
    """`help [页码]`：按 id 写法罗列命令，纯文本、不带按钮。"""

    text = " ".join(str(message or "").split())
    page = 1
    if text:
        parts = text.split()
        if len(parts) != 1 or not parts[0].isdecimal():
            await manager.send(reply.id_help_message(1))
            return
        page = int(parts[0])
    await manager.send(reply.id_help_message(page))


__all__ = []
