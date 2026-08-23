"""游戏命令统一注册入口。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from launch.adapter import MessageHandler

from .help_registry import HelpSpec, help_registry

GAME_METADATA_KEY = "game"
COMMAND_SCOPES = frozenset({"通用", "专属", "后台"})
_registered_commands: list[tuple[str, str, str, str]] = []
_registered_command_routes: list[tuple[str, str, str, str, str]] = []


class GameCommand:
    """给三种底层注册器补齐状态守卫和帮助契约。"""

    @staticmethod
    def fullmatch(
        cmd,
        *,
        aliases: Sequence[str] = (),
        scope: str,
        guard_rule: str,
        help: HelpSpec | None = None,
        hidden: bool = False,
        metadata: dict[str, Any] | None = None,
        priority: int = 100,
        block: bool = True,
    ) -> Callable:
        return _register(
            MessageHandler.fullmatch,
            cmd,
            aliases=aliases,
            scope=scope,
            guard_rule=guard_rule,
            help=help,
            hidden=hidden,
            metadata=metadata,
            priority=priority,
            block=block,
        )

    @staticmethod
    def command(
        cmd,
        *,
        aliases: Sequence[str] = (),
        scope: str,
        guard_rule: str,
        help: HelpSpec | None = None,
        hidden: bool = False,
        metadata: dict[str, Any] | None = None,
        priority: int = 100,
        block: bool = True,
    ) -> Callable:
        return _register(
            MessageHandler.command,
            cmd,
            aliases=aliases,
            scope=scope,
            guard_rule=guard_rule,
            help=help,
            hidden=hidden,
            metadata=metadata,
            priority=priority,
            block=block,
        )

    @staticmethod
    def regex(
        cmd,
        *,
        aliases: Sequence[str] = (),
        scope: str,
        guard_rule: str,
        help: HelpSpec | None = None,
        hidden: bool = False,
        metadata: dict[str, Any] | None = None,
        priority: int = 100,
        block: bool = True,
    ) -> Callable:
        return _register(
            MessageHandler.regex,
            cmd,
            aliases=aliases,
            scope=scope,
            guard_rule=guard_rule,
            help=help,
            hidden=hidden,
            metadata=metadata,
            priority=priority,
            block=block,
        )


def _register(
    registrar: Callable[..., Callable],
    cmd,
    *,
    aliases: Sequence[str],
    scope: str,
    guard_rule: str,
    help: HelpSpec | None,
    hidden: bool,
    metadata: dict[str, Any] | None,
    priority: int,
    block: bool,
) -> Callable:
    command_key = str(cmd or "").strip()
    if not command_key or any(char.isspace() for char in command_key):
        raise ValueError("游戏命令必须是一个不含空白的主命令")
    if len(command_key) > 4:
        raise ValueError("游戏主命令最多四个字；长写法请登记为 aliases")
    if isinstance(aliases, str):
        aliases = (aliases,)
    try:
        alias_values = tuple(str(alias or "").strip() for alias in aliases)
    except TypeError as exc:
        raise TypeError("aliases 必须是字符串序列") from exc
    if any(not alias or any(char.isspace() for char in alias) for alias in alias_values):
        raise ValueError("命令别名必须是不含空白的非空字符串")
    routes = (command_key, *alias_values)
    if len({route.casefold() for route in routes}) != len(routes):
        raise ValueError("主命令和别名不能重复")
    normalized_scope = str(scope or "").strip()
    if normalized_scope not in COMMAND_SCOPES:
        raise ValueError(f"游戏命令 scope 必须是：{'、'.join(sorted(COMMAND_SCOPES))}")
    if normalized_scope == "后台" and (not hidden or help is not None):
        raise ValueError("后台命令必须 hidden=True，且禁止登记玩家帮助")
    normalized_guard_rule = str(guard_rule or "").strip()
    if not normalized_guard_rule:
        raise ValueError("游戏命令必须显式声明状态守卫规则")
    if help is not None and hidden:
        raise ValueError("游戏命令不能同时登记帮助并标记为隐藏")
    if help is None and not hidden:
        raise ValueError("游戏命令必须提供 help=HelpSpec(...) 或 hidden=True")
    merged = dict(metadata or {})
    game_metadata = dict(merged.get(GAME_METADATA_KEY) or {})
    game_metadata["guard_rule"] = normalized_guard_rule
    game_metadata["scope"] = normalized_scope
    merged[GAME_METADATA_KEY] = game_metadata
    def decorate(func: Callable) -> Callable:
        source_module = func.__module__
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
        if help is not None:
            help_registry.register(routes, help, source_module=source_module)
        for route in routes:
            registrar(
                cmd=route,
                priority=priority,
                block=block,
                metadata=merged,
            )(func)
        _registered_commands.append(
            (command_key, normalized_scope, source_module, normalized_guard_rule)
        )
        _registered_command_routes.extend(
            (route, normalized_scope, source_module, normalized_guard_rule, command_key)
            for route in routes
        )
        decorated = func
        return decorated

    return decorate


def registered_guard_rules() -> tuple[str, ...]:
    """返回所有已加载游戏命令显式引用的守卫规则。"""

    return tuple(sorted({entry[3] for entry in _registered_commands}))


def registered_commands() -> tuple[tuple[str, str, str], ...]:
    """返回命令、声明范围和来源模块，供正式检查入口使用。"""

    return tuple(
        (command, scope, module) for command, scope, module, _ in _registered_commands
    )


def registered_command_routes() -> tuple[tuple[str, str, str], ...]:
    """返回主命令和别名的完整路由，供启动契约检查冲突。"""

    return tuple(
        (route, scope, module)
        for route, scope, module, _, _ in _registered_command_routes
    )


def unregister_command_module(module_name: str) -> None:
    """同步卸载一个命令模块在游戏层和全部驱动器中的旧登记。"""

    owner = str(module_name or "").strip()
    if not owner:
        raise ValueError("命令模块名不能为空")
    _registered_commands[:] = [
        entry for entry in _registered_commands if entry[2] != owner
    ]
    _registered_command_routes[:] = [
        entry for entry in _registered_command_routes if entry[2] != owner
    ]
    help_registry.unregister_module(owner)
    MessageHandler.unregister_module(owner)


__all__ = [
    "COMMAND_SCOPES",
    "GAME_METADATA_KEY",
    "GameCommand",
    "HelpSpec",
    "registered_command_routes",
    "registered_commands",
    "registered_guard_rules",
    "unregister_command_module",
]
