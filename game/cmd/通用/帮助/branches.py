"""正文的「一键多分支」：查看|借阅功法 400001。

同一份内容常常有好几条命令可用（查看、借阅、装配…）。以前每条各占一个无边框按钮，
又长又散。这里给一个统一写法：把分支词用 | 连在前面，后面跟**共享的参数尾巴**；
点一次回一个选择菜单，由玩家挑一条。

**只做选择，不代为派发**：框架没有「按命令串再派发」的公开口，代派发也会绕过玩家的
确认。回菜单既不用动 launch/，又能让每条分支按自己登记的 usage 决定「点了直接发」
还是「只填入」——还差参数的分支当然只能填。

**共享尾巴是硬约束**：两个分支的参数必须一样。查看/人物装配（参数不同）套不上这条语法。
"""
from __future__ import annotations

import re
from typing import Any

from message import M

from ...command import GameCommand
from ...help_registry import help_registry


BRANCH_PATTERN = re.compile(r"^(?P<branches>[^\s|]+(?:\|[^\s|]+)+)\s*(?P<tail>.*)$", re.DOTALL)


def branches_of(value: object) -> tuple[tuple[str, str], ...]:
    """把分支串解成 (命令词, 完整命令)；认不出的分支直接丢掉。"""

    match = BRANCH_PATTERN.match(" ".join(str(value or "").split()))
    if match is None:
        return ()
    tail = match.group("tail")
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for word in match.group("branches").split("|"):
        if not word or word in seen:
            continue
        seen.add(word)
        if help_registry.find(word) is None:
            continue
        result.append((word, (word + " " + tail).strip()))
    return tuple(result)


def is_complete(command: str) -> bool:
    """按当前参数这条命令是否已经完整——完整就直接发，不完整只填入。"""

    parts = command.split(" ")
    entry = help_registry.find(parts[0])
    if entry is None:
        return False
    return any(len(usage.split()) == len(parts) for usage in entry.spec.usage)


@GameCommand.regex(
    cmd=BRANCH_PATTERN,
    metadata={"scope": "通用", "guard_rule": "始终可用", "hidden": True},
)
async def choose_branch(raw_message: str, manager: Any) -> None:
    """回一个分支选择菜单。"""

    options = branches_of(raw_message)
    builder = (
        M.document().header("选择操作").section("这条命令有多个分支", icon="notice")
    )
    if len(options) < 2:
        builder.line(M.status("认不出", tone="warning"), " 分支词必须是已注册的命令。")
        await manager.send(builder.build())
        return
    for word, command in options:
        builder.line(M.command(word, command, submit=is_complete(command)))
    await manager.send(builder.build())


__all__ = ["BRANCH_PATTERN", "branches_of", "is_complete"]
