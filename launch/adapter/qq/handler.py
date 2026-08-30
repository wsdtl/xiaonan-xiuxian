"""QQ webhook 驱动器的对外入口与单条事件编排。"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from launch.config import config
from launch.log import C, logger

from ..base_handler import BaseMessageHandler
from ..command_guard import CommandGuardContext, run_command_guards
from ..context import (
    CONVERSATION_GROUP,
    CONVERSATION_PRIVATE,
    AdapterCapabilities,
    MessageContext,
    ReplyTarget,
    reset_current_message_context,
    set_current_message_context,
)
from ..depends import call_with_dependencies
from .client import client
from .event import QqMessageEvent, parse_message_event
from .manager import current_event, manager
from .rules import (
    QqCommandMatch,
    QqCommandRegistry,
    RegexCommands,
    TextCommands,
    normalize_regex_commands,
    normalize_text_commands,
)
from .runtime import QqDriverRuntime
from .signature import make_validation_signature

ACK_RESPONSE = {"op": 12}
_command_registry = QqCommandRegistry()
_runtime = QqDriverRuntime()


class QqEventHandler(BaseMessageHandler):
    """QQ 驱动器只编排 QQ 事件，不共享其他驱动器的会话运行时。"""

    CAPABILITIES = AdapterCapabilities(
        text=True,
        markdown=True,
        image=True,
        buttons=True,
        mention=True,
        private_message=True,
        group_message=True,
        active_push=True,
    )

    @staticmethod
    async def run() -> None:
        """整理 QQ 命令索引并启动本驱动器的后台运行时。"""

        if not client.app_id:
            logger.opt(colors=True).warning(f"{C.warn('QQ bot app_id 未配置')}")
        if not client.client_secret:
            logger.opt(colors=True).warning(
                f"{C.warn('QQ bot secret 未配置，开放平台回调验证会失败')}"
            )
        else:
            logger.opt(colors=True).success(f"{C.ok('QQ bot 已启用')}")

        _command_registry.build_index()
        await manager.start()
        await _runtime.start(
            process_event=QqEventHandler._process_message_event,
            event_log_parts=QqEventHandler._event_log_parts,
            short_id=QqEventHandler._short_id,
        )
        logger.opt(colors=True).success(
            C.join(
                C.ok("QQ webhook 已就绪"),
                C.kv(
                    "path",
                    (config.get("QQ_EVENT_PATH", "/qq/events") or "/qq/events").rstrip(
                        "/"
                    ),
                ),
                C.kv("fullmatch", _command_registry.fullmatch_count),
                C.kv("command", _command_registry.command_count),
                C.kv("regex", _command_registry.regex_rule_count),
                C.kv("workers", _runtime.settings.event_workers),
            )
        )

    @staticmethod
    async def shutdown() -> None:
        """关闭 QQ 自己的队列、线程池和回复管理器。"""

        await _runtime.shutdown()
        await manager.shutdown()

    @staticmethod
    async def dispatch(*args, **kwargs) -> dict:
        """BaseAdapter 入口：处理一份 QQ webhook payload。"""

        payload = kwargs.get("payload")
        if payload is None and args:
            payload = args[0]
        return await QqEventHandler.handle_webhook(payload)

    @staticmethod
    async def handle_webhook(payload: Any) -> dict:
        """快速确认 webhook，并把可解析消息送入 QQ 后台队列。"""

        if not isinstance(payload, dict):
            return ACK_RESPONSE

        event = parse_message_event(
            payload,
            bot_name=config.get("QQ_BOT_NAME", ""),
        )
        if event is not None:
            logger.opt(colors=True).debug(
                C.join(
                    C.ok("QQ webhook 已接收"),
                    *QqEventHandler._event_log_parts(event, include_message=False),
                )
            )
            _runtime.enqueue_interaction_ack(event)
            await _runtime.enqueue_event(event)
        else:
            event_type = str(payload.get("t") or "").strip()
            is_unparsed_interaction = event_type == "INTERACTION_CREATE"
            log = logger.opt(colors=True)
            write = log.warning if is_unparsed_interaction else log.debug
            write(
                C.join(
                    C.warn("QQ 按钮事件无法解析")
                    if is_unparsed_interaction
                    else C.ok("QQ webhook 已确认"),
                    *QqEventHandler._payload_log_parts(payload),
                )
            )
        return ACK_RESPONSE

    @staticmethod
    def fullmatch(
        cmd: TextCommands,
        priority: int = 0,
        block: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> Callable:
        """注册必须完整匹配整条消息的 QQ 回调。"""

        return QqEventHandler._callback_wrapper(
            normalize_text_commands(cmd),
            _command_registry.register_fullmatch,
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
        """注册命令词加参数的 QQ 回调。"""

        return QqEventHandler._callback_wrapper(
            normalize_text_commands(cmd),
            _command_registry.register_command,
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
        """注册完整消息正则 QQ 回调。"""

        return QqEventHandler._callback_wrapper(
            normalize_regex_commands(cmd),
            _command_registry.register_regex,
            priority,
            block,
            metadata,
        )

    @staticmethod
    def unregister_module(module_name: str) -> None:
        _command_registry.unregister_module(module_name)

    @staticmethod
    def _callback_wrapper(
        commands: list,
        registrar: Callable,
        priority: int,
        block: bool,
        metadata: dict[str, Any] | None,
    ) -> Callable:
        def wrapper(func: Callable) -> Callable:
            for command in commands:
                registrar(command, func, priority, block, metadata)
            return func

        return wrapper

    @staticmethod
    async def validation(payload: dict) -> dict:
        """处理 QQ 开放平台回调地址验证。"""

        data = payload.get("d")
        if not isinstance(data, dict):
            raise TypeError("QQ 回调验证缺少 d 对象")
        plain_token = str(data.get("plain_token") or "").strip()
        event_ts = str(data.get("event_ts") or "").strip()
        if not plain_token or not event_ts:
            raise ValueError("QQ 回调验证缺少 plain_token 或 event_ts")
        bot_secret = config.get("QQ_BOT_SECRET", "").strip()
        return {
            "plain_token": plain_token,
            "signature": make_validation_signature(bot_secret, plain_token, event_ts),
        }

    @staticmethod
    async def _process_message_event(event: QqMessageEvent) -> bool:
        """在 QQ 当前事件上下文中执行一条已经出队的消息。"""

        event_token = current_event.set(event)
        try:
            matched = _command_registry.match(event.content)
            if not matched:
                logger.opt(colors=True).debug(
                    C.join(
                        C.warn("QQ 消息未命中命令"),
                        *QqEventHandler._event_log_parts(event),
                    )
                )
                return False

            logger.opt(colors=True).success(
                C.join(
                    C.ok("QQ 命令命中"),
                    *QqEventHandler._event_log_parts(event),
                    C.kv("cmd", QqEventHandler._matched_commands_text(matched)),
                    C.kv("handlers", len(matched)),
                )
            )
            execution_plan = QqEventHandler._execution_plan(matched)
            if await QqEventHandler._guards_blocked(execution_plan, event):
                return True
            for item in execution_plan:
                await QqEventHandler._call_rule(item, event)
            return True
        finally:
            current_event.reset(event_token)

    @staticmethod
    def _execution_plan(matched: list[QqCommandMatch]) -> list[QqCommandMatch]:
        """按 block 规则截取本次消息真正可能执行的回调。"""

        planned: list[QqCommandMatch] = []
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
        items: list[QqCommandMatch], event: QqMessageEvent
    ) -> bool:
        """先校验全部待执行回调，再开始产生业务副作用。"""

        for item in items:
            if await QqEventHandler._guard_blocked(item, event):
                return True
        return False

    @staticmethod
    async def _guard_blocked(item: QqCommandMatch, event: QqMessageEvent) -> bool:
        message_context = QqEventHandler._message_context(item, event)
        context_token = set_current_message_context(message_context)
        try:
            decision = await run_command_guards(
                CommandGuardContext(
                    message_context=message_context,
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
    async def _call_rule(item: QqCommandMatch, event: QqMessageEvent) -> None:
        message_context = QqEventHandler._message_context(item, event)
        context_token = set_current_message_context(message_context)
        try:
            await call_with_dependencies(
                item.rule.func,
                {
                    "user_id": message_context.user_id,
                    "message": item.message,
                    "manager": manager,
                    "cmd": item.command,
                    "raw_message": event.content,
                    "message_context": message_context,
                    "sender_name": message_context.sender_name,
                    "reply_target": message_context.reply_target,
                    "adapter_capabilities": message_context.capabilities,
                    "match": item.match,
                },
            )
        finally:
            reset_current_message_context(context_token)

    @staticmethod
    def _message_context(item: QqCommandMatch, event: QqMessageEvent) -> MessageContext:
        conversation_type = (
            CONVERSATION_GROUP if event.is_group else CONVERSATION_PRIVATE
        )
        reply_target = ReplyTarget(
            adapter="qq",
            user_id=event.user_id,
            target_id=event.group_id or event.user_id,
            conversation_type=conversation_type,
            driver_target=event,
        )
        return MessageContext(
            adapter="qq",
            user_id=event.user_id,
            request_id=event.event_id or event.interaction_id or event.message_id,
            command=item.command,
            message=item.message,
            raw_message=event.content,
            conversation_type=conversation_type,
            reply_target=reply_target,
            capabilities=QqEventHandler.CAPABILITIES,
            driver_context=event,
            sender_name=event.sender_name,
        )

    @staticmethod
    def _payload_log_parts(payload: dict) -> list[str]:
        data = payload.get("d") if isinstance(payload.get("d"), dict) else {}
        return [
            C.kv("op", payload.get("op") or "-"),
            C.kv("type", payload.get("t") or "-"),
            C.kv("event", QqEventHandler._short_id(payload.get("id"))),
            C.kv("msg", QqEventHandler._short_id(data.get("id"))),
        ]

    @staticmethod
    def _event_log_parts(
        event: QqMessageEvent, include_message: bool = True
    ) -> list[str]:
        parts = [
            C.kv("type", QqEventHandler._event_type_label(event.event_type)),
            C.kv("user", QqEventHandler._short_id(event.user_id)),
            C.kv("group", QqEventHandler._short_id(event.group_id)),
            C.kv("msg", QqEventHandler._short_id(event.message_id)),
        ]
        if event.interaction_id:
            parts.append(
                C.kv("interaction", QqEventHandler._short_id(event.interaction_id))
            )
        if include_message:
            parts.append(C.kv("message", QqEventHandler._short_text(event.content)))
        return parts

    @staticmethod
    def _event_type_label(event_type: str) -> str:
        return {
            "C2C_MESSAGE_CREATE": "私聊",
            "GROUP_AT_MESSAGE_CREATE": "群艾特",
            "GROUP_MESSAGE_AT_CREATE": "群艾特",
            "GROUP_MESSAGE_CREATE": "群聊",
            "INTERACTION_CREATE": "按钮",
        }.get(event_type, event_type or "-")

    @staticmethod
    def _matched_commands_text(items: list[QqCommandMatch]) -> str:
        commands: list[str] = []
        seen: set[str] = set()
        for item in items:
            command = item.command or "-"
            if command in seen:
                continue
            seen.add(command)
            commands.append(command)
        if not commands:
            return "-"
        text = "、".join(commands[:3])
        if len(commands) > 3:
            text = f"{text} 等{len(commands)}个"
        return QqEventHandler._short_text(text, limit=60)

    @staticmethod
    def _short_id(value: object, head: int = 8, tail: int = 6) -> str:
        text = str(value or "").strip()
        if not text:
            return "-"
        if len(text) <= head + tail + 3:
            return text
        return f"{text[:head]}...{text[-tail:]}"

    @staticmethod
    def _short_text(value: object, limit: int = 80) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text:
            return "-"
        if len(text) <= limit:
            return text
        return f"{text[: limit - 1]}…"


__all__ = ["QqEventHandler", "manager"]
