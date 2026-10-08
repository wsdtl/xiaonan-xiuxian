"""正文的「一键多分支」：查看|借阅功法 400001。

同一份内容常常有好几条命令可用（查看、借阅、装配…）。以前每条各占一个无边框按钮，
又长又散。这里给一个统一写法：把分支词用 | 连在前面，后面跟**共享的参数尾巴**；
点一次回一个选择菜单，由玩家挑一条。

**只做选择，不代为派发**：框架没有「按命令串再派发」的公开口，代派发也会绕过玩家的
确认。回菜单既不用动 launch/，又能让每条分支按自己登记的 usage 决定「点了直接发」
还是「只填入」——还差参数的分支当然只能填。

**两种写法都行**：
- 分支词 + 共享尾巴：`查看|借阅功法 400001`（只写命令词的段继承共享尾巴）
- 每条分支自带完整命令：`查看 400001 | 人物装配 功法 400001 03`
"""
from __future__ import annotations

import re
from typing import Any

from message import M

from ...command import GameCommand
from ...help_registry import help_registry


# 只要整条消息里出现 | 就交给这里；命令词的合法性由注册表判，不靠正则。
BRANCH_PATTERN = re.compile(r"^(?P<text>[^\n]*\|[^\n]*)$")


def branches_of(value: object) -> tuple[tuple[str, str], ...]:
    """把分支串解成 (命令词, 完整命令)；认不出的分支直接丢掉。

    两种写法：分支词 + 共享尾巴（`查看|借阅功法 400001`），或每条分支自带完整命令
    （`查看 400001 | 人物装配 功法 400001 03`）。**只写命令词的段继承共享尾巴**——
    共享尾巴取最后一个自带参数的段的参数。
    """

    text = " ".join(str(value or "").split())
    if BRANCH_PATTERN.match(text) is None:
        return ()
    segments = [segment.strip() for segment in text.split("|")]
    shared = ""
    for segment in reversed(segments):
        if " " in segment:
            shared = segment.split(" ", 1)[1].strip()
            break
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for segment in segments:
        if not segment:
            continue
        word, _, tail = segment.partition(" ")
        if word in seen:
            continue
        seen.add(word)
        if help_registry.find(word) is None:
            continue
        result.append((word, (word + " " + (tail.strip() or shared)).strip()))
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
    priority=200,
    block=True,
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
