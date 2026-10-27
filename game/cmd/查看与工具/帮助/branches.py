"""「一键多分支」的隐藏入口：只把消息交给纯解析器。"""
from __future__ import annotations

from typing import Any

from ...branching import (
    BRANCH_PATTERN,
    BranchParseError,
    branch_error,
    branch_menu,
    parse_branches,
)
from ...command import GameCommand
from ...reply_composer import send_game_reply


@GameCommand.regex(
    cmd=BRANCH_PATTERN,
    priority=200,
    block=True,
    metadata={"scope": "通用", "guard_rule": "始终可用", "hidden": True},
)
async def choose_branch(raw_message: str, manager: Any) -> None:
    """回一个只填入、不发送的分支选择菜单。"""

    try:
        commands = parse_branches(raw_message)
    except BranchParseError as exc:
        await send_game_reply(branch_error(str(exc)))
        return
    await send_game_reply(branch_menu(commands))


__all__ = ["BRANCH_PATTERN", "BranchParseError", "parse_branches"]
