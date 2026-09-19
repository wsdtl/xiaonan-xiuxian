"""消息命令前置守卫。

驱动器只负责在命令回调执行前询问守卫；具体业务规则由注册方自己实现。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from inspect import isawaitable
from itertools import count
from typing import Any

from message import M, Message

from .context import MessageContext


@dataclass(frozen=True)
class CommandGuardContext:
    """一次命令守卫检查需要的公共上下文。"""

    message_context: MessageContext
    command_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def adapter(self) -> str:
        """触发命令的驱动器名。"""

        return self.message_context.adapter

    @property
    def user_id(self) -> str:
        """触发命令的统一游戏用户编号。"""

        return self.message_context.user_id

    @property
    def cmd(self) -> str:
        """本次匹配到的命令片段。"""

        return self.message_context.command

    @property
    def message(self) -> str:
        """移除命令片段后的业务参数。"""

        return self.message_context.message

    @property
    def raw_message(self) -> str:
        """驱动器规整后的完整命令文本。"""

        return self.message_context.raw_message

    @property
    def conversation_type(self) -> str:
        """公共会话类型：private 或 group。"""

        return self.message_context.conversation_type


@dataclass(frozen=True)
class CommandGuardDecision:
    """守卫检查结果。"""

    blocked: bool = False
    reply: Message | None = None
    reason: str = ""

    @staticmethod
    def allow() -> CommandGuardDecision:
        """构造放行决定。"""

        return CommandGuardDecision()

    @staticmethod
    def block(reply: Message | None = None, reason: str = "") -> CommandGuardDecision:
        """构造拦截决定，可携带一次统一回复。"""

        return CommandGuardDecision(blocked=True, reply=reply, reason=reason)


@dataclass(frozen=True)
class CommandGuardEntry:
    """一条已注册的守卫。"""

    name: str
    priority: int
    order: int
    guard: Callable[[CommandGuardContext], Any]


_guard_order = count()
_guards: dict[str, CommandGuardEntry] = {}


def register_command_guard(
    name: str,
    guard: Callable[[CommandGuardContext], Any],
    *,
    priority: int = 0,
) -> None:
    """注册一条命令守卫；同名注册会覆盖旧实现，避免重复叠加。"""

    normalized_name = str(name or "").strip()
    if not normalized_name:
        raise ValueError("命令守卫 name 不能为空")

    old = _guards.get(normalized_name)
    order = old.order if old is not None else next(_guard_order)
    _guards[normalized_name] = CommandGuardEntry(
        name=normalized_name,
        priority=int(priority),
        order=order,
        guard=guard,
    )


def unregister_command_guard(name: str) -> None:
    """移除一条命令守卫。"""

    _guards.pop(str(name or "").strip(), None)


def registered_command_guards() -> tuple[CommandGuardEntry, ...]:
    """返回当前已注册守卫，按执行顺序排序。"""

    return tuple(
        sorted(_guards.values(), key=lambda item: (-item.priority, item.order))
    )


async def run_command_guards(context: CommandGuardContext) -> CommandGuardDecision:
    """按优先级执行守卫；任一守卫拦截后立即停止。"""

    for entry in registered_command_guards():
        try:
            decision = entry.guard(context)
            if isawaitable(decision):
                decision = await decision
        except Exception:  # noqa: BLE001 - a broken guard must fail closed
            return CommandGuardDecision.block(
                _guard_error_message(),
                reason=f"命令守卫执行失败：{entry.name}",
            )

        normalized = _normalize_decision(decision)
        if normalized.blocked:
            return normalized

    return CommandGuardDecision.allow()


def _normalize_decision(decision: object) -> CommandGuardDecision:
    """守卫必须返回明确决定；未知返回值按失败关闭。"""

    if isinstance(decision, CommandGuardDecision):
        return decision
    return CommandGuardDecision.block(
        _guard_error_message(),
        reason="命令守卫返回了无效结果",
    )


def _guard_error_message() -> Message:
    return (
        M.document()
        .section("当前状态", icon="notice")
        .line(
            M.status("暂不可用", tone="danger"),
            " 命令暂时无法执行，请稍后重试。",
        )
        .build()
    )
