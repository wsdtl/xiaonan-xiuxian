"""QQ webhook 驱动器的对外入口与单条事件编排。

命令注册表、事件处理函数和事件队列都在 `launch.adapter.qq_protocol`，和网关
WebSocket 传输共用一份。本文件只保留 webhook 传输自己的东西：HTTP 入站的
快速 ACK、开放平台地址验证的签名响应，以及驱动器的生命周期。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from launch.config import config
from launch.log import C, logger

from ..base_handler import BaseMessageHandler
from ..qq_protocol import processor
from ..qq_protocol.client import client
from ..qq_protocol.event import parse_message_event
from ..qq_protocol.manager import manager
from ..qq_protocol.rules import (
    RegexCommands,
    TextCommands,
    normalize_regex_commands,
    normalize_text_commands,
)
from ..shared_dispatch import MessageDispatchMixin
from .signature import make_validation_signature

ACK_RESPONSE = {"op": 12}
TRANSPORT = "webhook"


class QqEventHandler(MessageDispatchMixin, BaseMessageHandler):
    """QQ webhook 驱动器。

    它只编排"开放平台把 HTTP 回调推过来"这一种入站方式。命令索引、事件
    队列、命令匹配和回复发送都由 qq 包内的共享模块提供，网关 WebSocket
    驱动器复用同一份实现。
    """

    @staticmethod
    async def run() -> None:
        """整理 QQ 命令索引并启动共享派发运行时。"""

        if not client.app_id:
            logger.opt(colors=True).warning(f"{C.warn('QQ bot app_id 未配置')}")
        if not client.client_secret:
            logger.opt(colors=True).warning(
                f"{C.warn('QQ bot secret 未配置，开放平台回调验证会失败')}"
            )
        else:
            logger.opt(colors=True).success(f"{C.ok('QQ bot 已启用')}")

        await processor.start_dispatch_runtime(TRANSPORT)
        logger.opt(colors=True).success(
            C.join(
                C.ok("QQ webhook 已就绪"),
                C.kv(
                    "path",
                    (config.get("QQ_EVENT_PATH", "/qq/events") or "/qq/events").rstrip(
                        "/"
                    ),
                ),
                *processor.registry_log_parts(),
                C.kv(
                    "workers",
                    processor.driver_runtime.settings.event_workers,
                ),
            )
        )

    @staticmethod
    async def shutdown() -> None:
        """关闭 webhook 传输；共享运行时由引用计数决定是否真正释放。"""

        await processor.stop_dispatch_runtime(TRANSPORT)

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

        event = parse_message_event(payload, bot_name=processor.bot_name())
        if event is not None:
            logger.opt(colors=True).debug(
                C.join(
                    C.ok("QQ webhook 已接收"),
                    *processor.event_log_parts(event, include_message=False),
                )
            )
            processor.driver_runtime.enqueue_interaction_ack(event)
            await processor.submit_event(event)
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
                    *processor.payload_log_parts(payload),
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
        """注册命令词加参数的 QQ 回调。"""

        return QqEventHandler._callback_wrapper(
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
        """注册完整消息正则 QQ 回调。"""

        return QqEventHandler._callback_wrapper(
            normalize_regex_commands(cmd),
            processor.registry.register_regex,
            priority,
            block,
            metadata,
        )

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


__all__ = ["ACK_RESPONSE", "QqEventHandler", "manager", "processor"]