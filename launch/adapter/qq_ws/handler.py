"""QQ 网关 WebSocket 驱动器入口。

与 webhook 驱动器（qq_wh）共用 `launch.adapter.qq_protocol` 里的命令注册表、
事件解析、守卫和回复管理器；本文件只负责生命周期与"把一条网关 payload 交给
共用队列"。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from launch.log import C, logger

from ..base_handler import BaseMessageHandler
from ..qq_protocol import processor
from ..qq_protocol.client import client
from ..qq_protocol.rules import (
    RegexCommands,
    TextCommands,
    normalize_regex_commands,
    normalize_text_commands,
)
from ..shared_dispatch import MessageDispatchMixin
from . import gateway
from .runtime import QqGatewayRuntime

TRANSPORT = "websocket"
_runtime = QqGatewayRuntime()


class QqWsEventHandler(MessageDispatchMixin, BaseMessageHandler):
    """QQ 网关 WebSocket 驱动器。

    三个注册器与 webhook 驱动器写入同一个 `processor.registry`；因此
    `.env` 里同时启用两种入站方式时，业务命令不会重复注册，也不会出现
    只对某一种入站生效的命令。
    """

    @staticmethod
    async def run() -> None:
        """启动网关长连接与共享派发运行时。"""

        await processor.start_dispatch_runtime(TRANSPORT)

        if not client.app_id or not client.client_secret:
            logger.opt(colors=True).error(
                C.join(
                    C.fail("QQ bot 凭据未配置，WebSocket 无法鉴权"),
                    C.kv("app_id", "已配置" if client.app_id else "缺失"),
                    C.kv("secret", "已配置" if client.client_secret else "缺失"),
                )
            )
            return

        try:
            intents = gateway.resolve_intents()
        except ValueError as exc:
            logger.opt(colors=True).error(
                C.join(C.fail("QQ WebSocket intent 配置无效"), C.kv("reason", exc))
            )
            return

        await _runtime.start(intents)
        logger.opt(colors=True).success(
            C.join(
                C.ok("QQ WebSocket 已启动"),
                *processor.registry_log_parts(),
                C.kv("intents", intents),
                C.kv("events", gateway.describe_intents(intents)),
            )
        )

    @staticmethod
    async def shutdown() -> None:
        """关闭网关连接；共享运行时由引用计数决定是否真正释放。"""

        await _runtime.shutdown()
        await processor.stop_dispatch_runtime(TRANSPORT)

    @staticmethod
    async def dispatch(*args, **kwargs) -> bool:
        """BaseAdapter 入口：处理一条来自网关的 payload。

        正常路径由 runtime 直接送入共享队列；保留这个入口是为了满足
        `BaseAdapter` 契约，同时让本地假网关和测试能单独驱动一条事件。
        """

        payload = kwargs.get("payload")
        if payload is None and args:
            payload = args[0]
        return await QqWsEventHandler.handle_payload(payload)

    @staticmethod
    async def handle_payload(payload: Any) -> bool:
        """把一条网关 payload 解析并送入共享队列。"""

        if not isinstance(payload, dict):
            logger.opt(colors=True).warning(C.warn("QQ WebSocket payload 不是对象"))
            return False

        opcode = payload.get("op")
        if opcode == gateway.OP_WEBHOOK_VERIFY:
            logger.opt(colors=True).warning(
                C.warn("QQ WebSocket 收到 webhook 专用验证事件，已忽略")
            )
            return False
        if opcode != gateway.OP_DISPATCH:
            logger.opt(colors=True).debug(
                C.join(
                    C.ok("QQ WebSocket 忽略非事件 payload"),
                    C.kv("op", opcode if opcode is not None else "-"),
                )
            )
            return False

        event_type, _data = gateway.payload_event(payload)
        event = processor.parse_gateway_event(payload, event_type)
        if event is None:
            return False

        processor.driver_runtime.enqueue_interaction_ack(event)
        await processor.submit_event(event)
        return True

    @staticmethod
    def fullmatch(
        cmd: TextCommands,
        priority: int = 0,
        block: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> Callable:
        """注册完整消息回调；与 webhook 驱动器共用同一张命令表。"""

        return QqWsEventHandler._callback_wrapper(
            normalize_text_commands(cmd),
            processor.registry.register_fullmatch,
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
        """注册命令词加参数回调；与 webhook 驱动器共用同一张命令表。"""

        return QqWsEventHandler._callback_wrapper(
            normalize_text_commands(cmd),
            processor.registry.register_command,
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
        """注册完整消息正则回调；与 webhook 驱动器共用同一张命令表。"""

        return QqWsEventHandler._callback_wrapper(
            normalize_regex_commands(cmd),
            processor.registry.register_regex,
            priority,
            block,
            metadata,
        )

    @staticmethod
    def runtime() -> QqGatewayRuntime:
        """返回本驱动器的连接运行时，供诊断和本地验证读取统计。"""

        return _runtime


__all__ = ["QqWsEventHandler"]
