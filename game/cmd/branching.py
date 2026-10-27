"""正文的「一键多分支」：纯结构解析与只填入菜单。

三套写法（只看结构，不查命令表）：
- 共享尾：`去|前往 天衡城` -> 两条都带 天衡城；只有最后一段可带参数。
- 全量：`查看 清心散|小还丹` -> 每段原样作为一条命令；裸段也可以。
- 共享头：`>使用 黄品功法 1|2|3` -> 第一段最后一个词是第一个值，前面全是前缀。

分支控件只按结构解析、只出菜单；不查命令是否存在、不判断能否执行、不发送。
分支串属于展示区：生成方必须用中文名/品级名，不写编号；编号只用于 help 与存储。
"""
from __future__ import annotations

import re
from typing import Any

from message import M

BRANCH_PATTERN = re.compile(r"^(?P<text>[^\n]*\|[^\n]*)$")
_SHARED_HEAD_MARKER = ">"


class BranchParseError(ValueError):
    """分支串不符合三套写法之一。"""


def parse_branches(value: object) -> tuple[str, ...]:
    """把分支串按结构还原成命令列表；不查命令表。"""

    text = " ".join(str(value or "").split())
    if not text or "|" not in text:
        raise BranchParseError("分支至少要有两条")
    if text.startswith(_SHARED_HEAD_MARKER):
        return _shared_head(text[len(_SHARED_HEAD_MARKER) :].strip())
    segments = _segments(text)
    if " " in segments[0]:
        return _full(segments)
    return _shared_tail(segments)


def _segments(text: object) -> tuple[str, ...]:
    segments = tuple(part.strip() for part in str(text or "").split("|"))
    if any(not part for part in segments):
        raise BranchParseError("分支段不能为空")
    if len(segments) < 2:
        raise BranchParseError("分支至少要有两条")
    return segments


def _shared_tail(segments: tuple[str, ...]) -> tuple[str, ...]:
    if any(" " in part for part in segments[:-1]):
        raise BranchParseError("共享尾写法里只有最后一段可以带参数")
    _last_word, separator, tail = segments[-1].partition(" ")
    shared = tail if separator else ""
    commands = [
        f"{part} {shared}".strip() if shared else part for part in segments[:-1]
    ]
    commands.append(segments[-1])
    return _finish(commands)


def _full(segments: tuple[str, ...]) -> tuple[str, ...]:
    return _finish(segments)


def _shared_head(text: str) -> tuple[str, ...]:
    segments = _segments(text)
    prefix, separator, first_value = segments[0].rpartition(" ")
    if not separator or not prefix or not first_value:
        raise BranchParseError("共享头写法第一段必须是「前缀 第一个值」")
    if any(" " in arg for arg in segments[1:]):
        raise BranchParseError("共享头写法后面每段只能是一个值")
    commands = [segments[0]]
    commands.extend(f"{prefix} {arg}" for arg in segments[1:])
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


def branch_menu(commands: tuple[str, ...]) -> Any:
    """把解析后的命令列成只填入菜单。"""

    builder = M.document().section("选择分支", icon="game.pin_doc")
    for index, command in enumerate(commands, start=1):
        builder.item(index, M.command(command, command))
    return builder.closing("点一条填入，确认后发送").build()


def branch_menu_for(value: object) -> Any:
    """解析并出菜单；结构不合法时由调用方捕获 BranchParseError。"""

    return branch_menu(parse_branches(value))


def branch_error(message: str) -> Any:
    """结构不合法的统一回执。"""

    return (
        M.document()
        .section("选择分支", icon="game.pin_doc")
        .line(M.status("写法不明确", tone="warning"), " ", message)
        .closing("分支只按结构解析；命令能否执行由后续命令链判断。")
        .build()
    )


__all__ = [
    "BRANCH_PATTERN",
    "BranchParseError",
    "branch_error",
    "branch_menu",
    "branch_menu_for",
    "parse_branches",
]
