"""游戏命令统一注册入口。"""

from __future__ import annotations


import re
import functools
from collections.abc import Callable, Mapping, Sequence
from itertools import count
from typing import Any

from launch.adapter import MessageHandler
from launch.adapter.command_cooldown import (
    COOLDOWN_FIELD,
    COOLDOWN_KEY_FIELD,
    COOLDOWN_NAME_FIELD,
)
from launch.adapter.depends import current_message_context

from message import (
    reset_command_title,
    reset_identity,
    set_command_title,
    set_identity,
)

from .help_icons import icon_for_command

from .help_registry import HelpSpec, help_registry

COMMAND_SCOPES = frozenset({"通用", "专属", "后台"})
#: 命令冷却键的序号源：装饰器每条注册取一个，与名字/别名/模块/适配器全都无关，天然唯一。
_cooldown_serial = count()
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
        cooldown: float = 0,
        metadata: dict[str, Any] | None = None,
    ) -> Callable:
        return _register(
            MessageHandler.fullmatch,
            cmd,
            priority=priority,
            block=block,
            cooldown=cooldown,
            metadata=metadata,
        )

    @staticmethod
    def command(
        cmd: object,
        *,
        priority: int = 100,
        block: bool = True,
        cooldown: float = 0,
        metadata: dict[str, Any] | None = None,
    ) -> Callable:
        return _register(
            MessageHandler.command,
            cmd,
            priority=priority,
            block=block,
            cooldown=cooldown,
            metadata=metadata,
        )

    @staticmethod
    def regex(
        cmd: object,
        *,
        priority: int = 100,
        block: bool = True,
        cooldown: float = 0,
        metadata: dict[str, Any] | None = None,
    ) -> Callable:
        return _register(
            MessageHandler.regex,
            cmd,
            priority=priority,
            block=block,
            cooldown=cooldown,
            metadata=metadata,
        )


async def _identity_text(user_id: str) -> str:
    """人物头的文案：昵称 境界 等级；没建档就写「未建档」。"""
    from game.app import current_game_services

    try:
        return await current_game_services().features.chakan_juese.identity_text(user_id)
    except Exception:  # noqa: BLE001 - 玩法没起也不该挡住回复
        return "未建档"


def _with_identity(func: Callable) -> Callable:
    """统一回复层给每条回执加人物头与主标题；业务函数不得手写。"""

    @functools.wraps(func)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        context = current_message_context()
        user_id = str(kwargs.get("user_id") or "")
        if not user_id:
            # 有些命令的签名里没有 user_id，框架就不会注入；从消息上下文兜底。
            user_id = str(getattr(context, "user_id", "") or "")
        token = set_identity(await _identity_text(user_id)) if user_id else None
        # 主标题＝玩家触发时那句命令原文（含参数），图标按命令的帮助分类取；非命令消息不设。
        raw = str(getattr(context, "raw_message", "") or "").strip()
        title_token = (
            set_command_title(raw, icon=icon_for_command(getattr(context, "command", "")))
            if raw
            else None
        )
        try:
            return await func(*args, **kwargs)
        finally:
            if token is not None:
                reset_identity(token)
            if title_token is not None:
                reset_command_title(title_token)

    return wrapped


def _register(
    registrar: Callable[..., Callable],
    cmd: object,
    *,
    priority: int,
    block: bool,
    cooldown: float = 0,
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
    # 命令冷却：只在这一处写保留键。同一份 metadata 会交给这条命令的**每个别名**与**每个适配器**，
    # 所以别名之间自动共用同一个冷却键（换别名绕不过去）。没设冷却（cooldown=0）的命令不碰这份 dict。
    if cooldown > 0:
        command_metadata[COOLDOWN_FIELD] = float(cooldown)
        command_metadata[COOLDOWN_KEY_FIELD] = f"cd-{next(_cooldown_serial)}"
        command_metadata[COOLDOWN_NAME_FIELD] = command_key
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
        wrapped = _with_identity(func)
        for route in routes:
            registrar(
                cmd=route, priority=priority, block=block, metadata=command_metadata
            )(wrapped)
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
