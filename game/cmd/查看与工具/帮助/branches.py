"""正文的「一键多分支」：纯解析 + 只填入菜单。

三套写法（只按结构还原；命令词必须是已注册的公开命令，但不校验用法与守卫）：
- 共享尾：`去|前往 天衡城` -> 两条都带 天衡城；只有最后一段可带参数。
- 全量：`查看 清心散|取消托管` -> 每段一条完整命令；裸命令也可以，但必须本身是命令。
- 共享头：`>查看 清心散|小还丹` -> 第一段是「命令 一个参数」，后面每段是同命令的另一个单参数。

分支控件只做解析和菜单：不判断命令能否执行、不发送；菜单每条只填入。
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from message import M

from ...command import GameCommand
from ...help_registry import help_registry
from ...reply_composer import send_game_reply


# 只要整条消息里出现 | 就交给这里；命令词只用来识别分支，能否执行由后续正常命令链判断。
BRANCH_PATTERN = re.compile(r"^(?P<text>[^\n]*\|[^\n]*)$")
_SHARED_HEAD_MARKER = ">"
CommandWord = Callable[[str], bool]


class BranchParseError(ValueError):
    """分支串不符合三套写法之一。"""


def parse_branches(
    value: object, *, known: CommandWord | None = None
) -> tuple[str, ...]:
    """把分支串按结构还原成命令列表。

    `known` 只回答「这个词是不是命令词」，不回答「这条命令现在能不能用」。
    生产默认查公开命令表；测试可以注入自己的命令词集合。
    """

    is_command = known or _registered
    text = " ".join(str(value or "").split())
    if not text or "|" not in text:
        raise BranchParseError("分支至少要有两条")
    if text.startswith(_SHARED_HEAD_MARKER):
        return _shared_head(text[len(_SHARED_HEAD_MARKER) :].strip(), is_command)
    segments = _segments(text)
    if " " in segments[0]:
        return _full(segments, is_command)
    return _shared_tail(segments, is_command)


def _registered(word: str) -> bool:
    return help_registry.find(word) is not None


def _segments(text: object) -> tuple[str, ...]:
    segments = tuple(part.strip() for part in str(text or "").split("|"))
    if any(not part for part in segments):
        raise BranchParseError("分支段不能为空")
    if len(segments) < 2:
        raise BranchParseError("分支至少要有两条")
    return segments


def _require_commands(
    segments: tuple[str, ...], is_command: CommandWord
) -> None:
    for segment in segments:
        word = segment.split(" ", 1)[0]
        if not is_command(word):
            raise BranchParseError(f"「{word}」不是命令")


def _shared_tail(
    segments: tuple[str, ...], is_command: CommandWord
) -> tuple[str, ...]:
    _require_commands(segments, is_command)
    if any(" " in part for part in segments[:-1]):
        raise BranchParseError("共享尾写法里只有最后一段可以带参数")
    _last_word, separator, tail = segments[-1].partition(" ")
    shared = tail if separator else ""
    commands = [
        f"{part} {shared}".strip() if shared else part for part in segments[:-1]
    ]
    commands.append(segments[-1])
    return _finish(commands)


def _full(segments: tuple[str, ...], is_command: CommandWord) -> tuple[str, ...]:
    _require_commands(segments, is_command)
    return _finish(segments)


def _shared_head(text: str, is_command: CommandWord) -> tuple[str, ...]:
    segments = _segments(text)
    if segments[0].count(" ") != 1:
        raise BranchParseError("共享头写法第一段必须是「命令 一个参数」")
    word, separator, first_arg = segments[0].partition(" ")
    if not separator or not first_arg:
        raise BranchParseError("共享头写法第一段必须是「命令 一个参数」")
    if not is_command(word):
        raise BranchParseError(f"「{word}」不是命令")
    if any(" " in arg for arg in segments[1:]):
        raise BranchParseError("共享头写法后面每段只能是一个参数")
    commands = [segments[0]]
    commands.extend(f"{word} {arg}" for arg in segments[1:])
    return _finish(commands)


def _finish(commands: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    for command in commands:
        value = command.strip()
        if value and value not in unique:
            unique.append(value)
    if len(unique) < 2:
        raise BranchParseError("分支至少要有两条")
    return tuple(unique)


def _menu(commands: tuple[str, ...]) -> Any:
    builder = M.document().section("选择分支", icon="game.pin_doc")
    for index, command in enumerate(commands, start=1):
        builder.item(index, M.command(command, command))
    return builder.closing("点一条填入，确认后发送").build()


def _error(message: str) -> Any:
    return (
        M.document()
        .section("选择分支", icon="game.pin_doc")
        .line(M.status("写法不明确", tone="warning"), " ", message)
        .closing("分支只解析写法；命令能否执行由后续命令链判断。")
        .build()
    )


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
        await send_game_reply(_error(str(exc)))
        return
    await send_game_reply(_menu(commands))


__all__ = ["BRANCH_PATTERN", "BranchParseError", "parse_branches"]
