"""各消息驱动器共用的回调注册包装与守卫编排。

QQ 与 Local 两个驱动器各自维护命令索引、消息会话、排队和回复状态，这部分
**故意不共享**。但"把注册项绑定到业务回调""按 block 规则截取执行计划"
"先统一过守卫再产生副作用"以及把命令参数注入业务函数，这几段与驱动器会话
无关，此前在每个驱动器里各写一份，已经出现过不一致（截断符一处 `…`、
一处 `...`），因此集中在这里。

各驱动器通过显式参数提供自己的差异，而不是让共享代码反向依赖驱动器：

- `message_context`：由驱动器生成自己的 `MessageContext`；
- `manager`：驱动器自己的回复管理器；
- `raw_message`：驱动器事件里的原始正文。

这些方法全部是 `@staticmethod`：框架通过 `AdapterSpec.handler` 这个类对象
调用它们（`spec.handler.run()`），改成实例方法会改变调用约定。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .command_guard import CommandGuardContext, run_command_guards
from .context import MessageContext, reset_current_message_context, set_current_message_context
from .depends import call_with_dependencies

MessageContextFactory = Callable[[Any, Any], MessageContext]


class MessageDispatchMixin:
    """驱动器共用的注册包装、执行计划、守卫编排与参数注入。"""

    @staticmethod
    def _callback_wrapper(
        commands: list,
        registrar: Callable,
        priority: int,
        block: bool,
        metadata: dict[str, Any] | None,
    ) -> Callable:
        """把已校验的注册项绑定到业务回调。"""

        def wrapper(func: Callable) -> Callable:
            for command in commands:
                registrar(command, func, priority, block, metadata)
            return func

        return wrapper

    @staticmethod
    def _execution_plan(matched: list[Any]) -> list[Any]:
        """按 block 规则截取本次消息真正可能执行的回调。"""

        planned: list[Any] = []
        block_priority: int | None = None
        for item in matched:
            if block_priority is not None and item.rule.priority < block_priority:
                break
            planned.append(item)
            if item.rule.block:
                block_priority = item.rule.priority
        return planned

    @staticmethod
    async def _guards_blocked(
        items: list[Any],
        event: Any,
        *,
        message_context: MessageContextFactory,
        manager: Any,
    ) -> bool:
        """先校验全部待执行回调，避免守卫失败前出现部分业务副作用。"""

        for item in items:
            if await MessageDispatchMixin._guard_blocked(
                item, event, message_context=message_context, manager=manager
            ):
                return True
        return False

    @staticmethod
    async def _guard_blocked(
        item: Any,
        event: Any,
        *,
        message_context: MessageContextFactory,
        manager: Any,
    ) -> bool:
        """执行一条待调用规则自己的命令守卫，必要时发送守卫回复。"""

        context = message_context(item, event)
        context_token = set_current_message_context(context)
        try:
            decision = await run_command_guards(
                CommandGuardContext(
                    message_context=context,
                    command_metadata=item.rule.metadata,
                )
            )
            if not decision.blocked:
                return False
            if decision.reply is not None:
                await manager.send(decision.reply)
            return True
        finally:
            reset_current_message_context(context_token)

    @staticmethod
    async def _call_rule(
        item: Any,
        event: Any,
        *,
        message_context: MessageContextFactory,
        manager: Any,
        raw_message: str,
    ) -> None:
        """把驱动器事件上下文转换成业务函数可接收的参数并调用。"""

        context = message_context(item, event)
        context_token = set_current_message_context(context)
        try:
            await call_with_dependencies(
                item.rule.func,
                {
                    "user_id": context.user_id,
                    "message": item.message,
                    "manager": manager,
                    "cmd": item.command,
                    "raw_message": raw_message,
                    "message_context": context,
                    "sender_name": context.sender_name,
                    "reply_target": context.reply_target,
                    "match": item.match,
                },
            )
        finally:
            reset_current_message_context(context_token)

    @staticmethod
    def _short_text(value: object, limit: int = 80) -> str:
        """压缩日志正文长度。

        截断符统一为单字符省略号：此前 QQ 用 `…`、Local 用 `...`，同一功能
        在两处产生不同输出。
        """

        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text:
            return "-"
        if len(text) <= limit:
            return text
        return f"{text[: limit - 1]}…"


__all__ = ["MessageDispatchMixin", "MessageContextFactory"]
