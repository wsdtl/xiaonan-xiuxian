"""QQ 网关 WebSocket 驱动器包导出（`qq_ws`）。

只导出这条传输自己的东西：网关 opcode、intents 解释、连接运行时与事件
处理器。命令、回复和目标构造等 QQ 协议能力在 `launch.adapter.qq_protocol`，
底层帧与连接在框架级 `launch.adapter.websocket`。
"""

from __future__ import annotations

from .gateway import describe_intents as describe_intents
from .gateway import resolve_intents as resolve_intents
from .handler import QqWsEventHandler as QqWsEventHandler
from .runtime import QqGatewayRuntime as QqGatewayRuntime
from .runtime import QqWsSession as QqWsSession
from .runtime import QqWsSettings as QqWsSettings
from .runtime import QqWsStats as QqWsStats


def runtime() -> QqGatewayRuntime:
    """返回当前驱动器的连接运行时。"""

    return QqWsEventHandler.runtime()


__all__ = [
    "QqGatewayRuntime",
    "QqWsEventHandler",
    "QqWsSession",
    "QqWsSettings",
    "QqWsStats",
    "describe_intents",
    "resolve_intents",
    "runtime",
]
