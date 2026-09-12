"""本地命令驱动器。"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from re import Pattern
from typing import Any, ClassVar

from launch.log import C, logger
from launch.message_events import emit_message_event, event_from_incoming

from ..base_handler import BaseMessageHandler
from ..context import (
    CONVERSATION_PRIVATE,
    MessageContext,
    ReplyTarget,
)
from ..shared_dispatch import MessageDispatchMixin
from .event import LocalCommandEvent, local_command_event
from .manager import LocalDispatchResult, current_event, manager

TextCommands = str | list[str] | tuple[str, ...]
RegexCommands = Pattern | list[Pattern] | tuple[Pattern, ...]


@dataclass(frozen=True)
class LocalCommandRule:
    """一条本地命令规则。"""

    func: Callable
    priority: int
    block: bool
    order: int
    pattern: Pattern | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalCommandMatch:
    """本地消息命中命令后的临时结果。"""

    rule: LocalCommandRule
    command: str
    message: str
    match: re.Match | None = None


class LocalEventHandler(MessageDispatchMixin, BaseMessageHandler):
    """本地触发文本驱动器。"""

    command_rules: ClassVar[dict[str, list[LocalCommandRule]]] = {}
    fullmatch_rules: ClassVar[dict[str, list[LocalCommandRule]]] = {}
    regex_rules: ClassVar[dict[str, list[LocalCommandRule]]] = {}
    regex_fallback: ClassVar[list[LocalCommandRule]] = []
    regex_prefix_lengths: ClassVar[set[int]] = set()
    _register_order: int = 0

    @staticmethod
    async def run() -> None:
        """启动时整理命令索引。"""

        LocalEventHandler._build_command_index()

    @staticmethod
    async def shutdown() -> None:
        """关闭本地驱动器。"""

        await manager.shutdown()

    @staticmethod
    async def dispatch(
        event: LocalCommandEvent | None = None,
        *,
        user_id: str = "",
        raw_message: str = "",
        sender_name: str = "",
        conversation_type: str = CONVERSATION_PRIVATE,
        event_id: str = "",
    ) -> LocalDispatchResult:
        """分发一条本地命令事件。"""

        if event is None:
            event = local_command_event(
                user_id=user_id,
                raw_message=raw_message,
                sender_name=sender_name,
                conversation_type=conversation_type,
                event_id=event_id,
            )
        result = LocalDispatchResult(event=event)
        result_token = manager.bind_result(result)
        event_token = current_event.set(event)
        try:
            emit_message_event(
                event_from_incoming(
                    adapter="local",
                    user_id=event.user_id,
                    request_id=event.event_id,
                    message_type="text",
                    content=event.raw_message,
                    sender_name=event.sender_name,
                )
            )
            matched = await LocalEventHandler._match_event(event)
            result.matched = bool(matched)
            result.matched_count = len(matched)
            if not matched:
                logger.opt(colors=True).debug(
                    C.join(
                        C.warn("本地消息未命中命令"),
                        C.kv("user", event.user_id or "-"),
                        C.kv(
                            "message", LocalEventHandler._short_text(event.raw_message)
                        ),
                    )
                )
                return result

            execution_plan = LocalEventHandler._execution_plan(matched)
            if await LocalEventHandler._guards_blocked(
                execution_plan,
                event,
                message_context=LocalEventHandler._message_context,
                manager=manager,
            ):
                return result

            for item in execution_plan:
                await LocalEventHandler._call_rule(
                    item,
                    event,
                    message_context=LocalEventHandler._message_context,
                    manager=manager,
                    raw_message=event.raw_message,
                )

            return result
        finally:
            current_event.reset(event_token)
            manager.reset_result(result_token)

    @staticmethod
    def fullmatch(
        cmd: TextCommands,
        priority: int = 0,
        block: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> Callable:
        """注册完整消息回调。"""

        return LocalEventHandler._callback_wrapper(
            LocalEventHandler._normalize_text_commands(cmd),
            LocalEventHandler._register_fullmatch_command,
            priority,
            block,
            metadata,
        )

    @staticmethod
    def command(
        cmd: TextCommands,
        priority: int = 0,
        block: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> Callable:
        """注册命令词加参数回调。"""

        return LocalEventHandler._callback_wrapper(
            LocalEventHandler._normalize_text_commands(cmd),
            LocalEventHandler._register_command,
            priority,
            block,
            metadata,
        )

    @staticmethod
    def regex(
        cmd: RegexCommands,
        priority: int = 0,
        block: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> Callable:
        """注册完整消息正则回调。"""

        return LocalEventHandler._callback_wrapper(
            LocalEventHandler._normalize_regex_commands(cmd),
            LocalEventHandler._register_regex_command,
            priority,
            block,
            metadata,
        )

    @staticmethod
    async def _match_event(event: LocalCommandEvent) -> list[LocalCommandMatch]:
        """按本地消息正文匹配已注册命令。"""

        command_text = event.raw_message.strip()
        if not command_text:
            return []

        matched: list[LocalCommandMatch] = [
            LocalCommandMatch(rule=rule, command=command_text, message="")
            for rule in LocalEventHandler.fullmatch_rules.get(command_text, [])
        ]
        command, message = LocalEventHandler._split_command(command_text)
        matched.extend(
            LocalCommandMatch(rule=rule, command=command, message=message)
            for rule in LocalEventHandler.command_rules.get(command, [])
        )

        for rule, match in await LocalEventHandler._match_regex_command(command_text):
            matched.append(
                LocalCommandMatch(
                    rule=rule,
                    command=command_text,
                    message="",
                    match=match,
                )
            )

        matched.sort(key=lambda item: (-item.rule.priority, item.rule.order))
        return matched

    @staticmethod
    def _message_context(
        item: LocalCommandMatch, event: LocalCommandEvent
    ) -> MessageContext:
        """生成本地驱动器的显式消息上下文。"""

        reply_target = ReplyTarget(
            adapter="local",
            user_id=event.user_id,
            target_id=event.user_id,
            conversation_type=event.conversation_type,
            driver_target=event,
        )
        return MessageContext(
            adapter="local",
            user_id=event.user_id,
            request_id=event.event_id,
            command=item.command,
            message=item.message,
            raw_message=event.raw_message,
            conversation_type=event.conversation_type,
            reply_target=reply_target,
            sender_name=event.sender_name,
        )

    @staticmethod
    def _build_command_index() -> None:
        """整理命令索引和排序。"""

        LocalEventHandler.regex_prefix_lengths = {
            len(prefix) for prefix in LocalEventHandler.regex_rules
        }

        for rules in LocalEventHandler.command_rules.values():
            rules.sort(key=lambda rule: (-rule.priority, rule.order))
        for rules in LocalEventHandler.fullmatch_rules.values():
            rules.sort(key=lambda rule: (-rule.priority, rule.order))
        for rules in LocalEventHandler.regex_rules.values():
            rules.sort(key=lambda rule: (-rule.priority, rule.order))
        LocalEventHandler.regex_fallback.sort(
            key=lambda rule: (-rule.priority, rule.order)
        )

    @staticmethod
    def _split_command(raw_message: str) -> tuple[str, str]:
        """按第一个空格拆出命令片段和业务参数文本。"""

        parts = raw_message.split(maxsplit=1)
        if len(parts) == 1:
            return raw_message, ""
        return parts[0], parts[1].strip()

    @staticmethod
    def _register_command(
        cmd: str,
        func: Callable,
        priority: int,
        block: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """注册命令词加参数回调。"""

        command = cmd.strip()
        if not command or any(char.isspace() for char in command):
            raise ValueError("command 注册器需要一个不含空白的命令词")
        rule = LocalEventHandler._make_rule(
            func=func, priority=priority, block=block, metadata=metadata
        )
        LocalEventHandler.command_rules[command] = LocalEventHandler._replace_owned(
            LocalEventHandler.command_rules.get(command, []), rule
        )

    @staticmethod
    def _register_fullmatch_command(
        cmd: str,
        func: Callable,
        priority: int,
        block: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """注册必须完整匹配整条消息的回调。"""

        command = cmd.strip()
        if not command:
            raise ValueError("fullmatch 注册器不接受空命令")
        rule = LocalEventHandler._make_rule(
            func=func, priority=priority, block=block, metadata=metadata
        )
        LocalEventHandler.fullmatch_rules[command] = LocalEventHandler._replace_owned(
            LocalEventHandler.fullmatch_rules.get(command, []), rule
        )

    @staticmethod
    def _register_regex_command(
        pattern: Pattern,
        func: Callable,
        priority: int,
        block: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """注册正则命令，并尝试按固定前缀建立候选索引。"""

        prefix = LocalEventHandler._extract_literal_prefix(pattern.pattern)
        rule = LocalEventHandler._make_rule(
            func=func,
            priority=priority,
            block=block,
            pattern=pattern,
            metadata=metadata,
        )
        if prefix:
            key = prefix.casefold()
            LocalEventHandler.regex_rules[key] = LocalEventHandler._replace_owned(
                LocalEventHandler.regex_rules.get(key, []), rule
            )
        else:
            LocalEventHandler.regex_fallback = LocalEventHandler._replace_owned(
                LocalEventHandler.regex_fallback, rule
            )

    @staticmethod
    def _replace_owned(
        rules: list[LocalCommandRule], rule: LocalCommandRule
    ) -> list[LocalCommandRule]:
        owner = rule.func.__module__
        return [value for value in rules if value.func.__module__ != owner] + [rule]

    @staticmethod
    def _make_rule(
        func: Callable,
        priority: int,
        block: bool,
        pattern: Pattern | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LocalCommandRule:
        """创建命令规则，并记录注册顺序。"""

        order = LocalEventHandler._register_order
        LocalEventHandler._register_order += 1
        return LocalCommandRule(
            func=func,
            priority=priority,
            block=block,
            order=order,
            pattern=pattern,
            metadata=dict(metadata or {}),
        )

    @staticmethod
    async def _match_regex_command(cmd: str) -> list[tuple[LocalCommandRule, re.Match]]:
        """对完整消息执行正则匹配。"""

        matched = []
        key = cmd.casefold()
        seen_rules: set[int] = set()

        for length in LocalEventHandler.regex_prefix_lengths:
            for rule in LocalEventHandler.regex_rules.get(key[:length], []):
                rule_id = id(rule)
                if rule_id in seen_rules:
                    continue

                seen_rules.add(rule_id)
                match = (
                    rule.pattern.fullmatch(cmd) if rule.pattern is not None else None
                )
                if match:
                    matched.append((rule, match))

        for rule in LocalEventHandler.regex_fallback:
            rule_id = id(rule)
            if rule_id in seen_rules:
                continue

            seen_rules.add(rule_id)
            match = rule.pattern.fullmatch(cmd) if rule.pattern is not None else None
            if match:
                matched.append((rule, match))

        return matched

    @staticmethod
    def _extract_literal_prefix(source: str) -> str:
        """从正则源码中提取开头固定文字。"""

        index = 1 if source.startswith("^") else 0
        prefix = []
        metacharacters = set(".^$*+?{}[]|()")

        while index < len(source):
            char = source[index]

            if char in metacharacters:
                break

            if char == "\\":
                if index + 1 >= len(source):
                    break

                next_char = source[index + 1]
                if next_char in "AbBdDsSwWZ0123456789":
                    break

                prefix.append(next_char)
                index += 2
                continue

            prefix.append(char)
            index += 1

        return "".join(prefix)

    @staticmethod
    def _normalize_text_commands(value: TextCommands) -> list[str]:
        """按声明顺序整理字符串命令。"""

        commands = list(value) if isinstance(value, (list, tuple)) else [value]
        if any(not isinstance(command, str) for command in commands):
            raise TypeError("fullmatch 和 command 注册器只支持字符串命令")
        return commands

    @staticmethod
    def _normalize_regex_commands(value: RegexCommands) -> list[Pattern]:
        """按声明顺序整理正则命令。"""

        commands = list(value) if isinstance(value, (list, tuple)) else [value]
        if any(not isinstance(command, re.Pattern) for command in commands):
            raise TypeError("regex 注册器只支持 re.Pattern")
        return commands
