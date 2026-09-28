"""游戏命令统一注册入口。"""

from __future__ import annotations


import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from launch.adapter import MessageHandler

from .help_registry import HelpSpec, help_registry

COMMAND_SCOPES = frozenset({"通用", "专属", "后台"})
_registered_commands: list[tuple[str, str, str, str]] = []
_registered_command_routes: list[tuple[str, str, str, str, str]] = []


class GameCommand:
    """在底层命令注册器上统一收集游戏命令元数据。"""

    @staticmethod
    def fullmatch(
        cmd: object,
        *,
        priority: int = 100,
        block: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> Callable:
        return _register(
            MessageHandler.fullmatch,
            cmd,
            priority=priority,
            block=block,
            metadata=metadata,
        )

    @staticmethod
    def command(
        cmd: object,
        *,
        priority: int = 100,
        block: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> Callable:
        return _register(
            MessageHandler.command,
            cmd,
            priority=priority,
            block=block,
            metadata=metadata,
        )

    @staticmethod
    def regex(
        cmd: object,
        *,
        priority: int = 100,
        block: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> Callable:
        return _register(
            MessageHandler.regex, cmd, priority=priority, block=block, metadata=metadata
        )


def _register(
    registrar: Callable[..., Callable],
    cmd: object,
    *,
    priority: int,
    block: bool,
    metadata: dict[str, Any] | None,
) -> Callable:
    is_regex = registrar is MessageHandler.regex
    if is_regex:
        routes = (
            (cmd,) if isinstance(cmd, re.Pattern)
            else tuple(cmd) if isinstance(cmd, Sequence)
            else ()
        )
        if not routes or any(not isinstance(route, re.Pattern) for route in routes):
            raise TypeError("正则命令 cmd 必须是正则表达式或正则表达式序列")
        route_names = tuple(route.pattern for route in routes)
    else:
        routes = route_names = _command_routes(cmd)
    command_key = route_names[0]
    command_metadata = dict(metadata or {})
    scope = _required_text(command_metadata, "scope")
    if scope not in COMMAND_SCOPES:
        raise ValueError(f"游戏命令 scope 必须是：{'、'.join(sorted(COMMAND_SCOPES))}")
    guard_rule = _required_text(command_metadata, "guard_rule")
    hidden = bool(command_metadata.get("hidden", False))
    help_spec = _help_spec(command_metadata.get("help"))
    if scope == "后台" and (not hidden or help_spec is not None):
        raise ValueError("后台命令必须在 metadata 标记 hidden=True，且禁止登记玩家帮助")
    if help_spec is not None and hidden and not is_regex:
        raise ValueError("游戏命令不能同时登记帮助并标记为隐藏")
    if help_spec is None and not hidden:
        raise ValueError("游戏命令必须在 metadata 提供 help，或标记 hidden=True")

    def decorate(func: Callable) -> Callable:
        source_module = func.__module__
        if not is_regex:
            _registered_commands[:] = [
                entry
                for entry in _registered_commands
                if (entry[0], entry[2]) != (command_key, source_module)
            ]
            _registered_command_routes[:] = [
                entry
                for entry in _registered_command_routes
                if not (entry[4] == command_key and entry[2] == source_module)
            ]
        if help_spec is not None:
            help_registry.register(route_names, help_spec, source_module=source_module)
        for route in routes:
            registrar(
                cmd=route, priority=priority, block=block, metadata=command_metadata
            )(func)
        _registered_commands.append((command_key, scope, source_module, guard_rule))
        _registered_command_routes.extend(
            (route, scope, source_module, guard_rule, command_key) for route in route_names
        )
        return func

    return decorate


def _command_routes(cmd: object) -> tuple[str, ...]:
    values: Sequence[object] = (
        (cmd,) if isinstance(cmd, str) else cmd if isinstance(cmd, Sequence) else ()
    )
    if not values:
        raise TypeError("游戏命令 cmd 必须是字符串或字符串序列")
    routes = tuple(str(value or "").strip() for value in values)
    if any(not route or any(char.isspace() for char in route) for route in routes):
        raise ValueError("游戏命令必须是不含空白的非空字符串")
    if len(routes[0]) > 4:
        raise ValueError("游戏主命令最多四个字；长写法可放在 cmd 后续项")
    if len({route.casefold() for route in routes}) != len(routes):
        raise ValueError("同一 cmd 中不能重复声明命令")
    return routes


def _required_text(metadata: Mapping[str, Any], key: str) -> str:
    value = str(metadata.get(key) or "").strip()
    if not value:
        raise ValueError(f"游戏命令 metadata 缺少 {key}")
    return value


def _help_spec(value: object) -> HelpSpec | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("游戏命令 metadata.help 必须是字典")
    return HelpSpec(
        category=value.get("category", ""),
        summary=value.get("summary", ""),
        usage=tuple(value.get("usage") or ()),
        side_effect=value.get("side_effect", ""),
        order=value.get("order", 100),
    )


def registered_guard_rules() -> tuple[str, ...]:
    return tuple(sorted({entry[3] for entry in _registered_commands}))


def registered_commands() -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (command, scope, module) for command, scope, module, _ in _registered_commands
    )


def registered_command_routes() -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (route, scope, module)
        for route, scope, module, _, _ in _registered_command_routes
    )


__all__ = [
    "COMMAND_SCOPES",
    "GameCommand",
    "registered_command_routes",
    "registered_commands",
    "registered_guard_rules",
]
