"""NapCat WebSocket 客户端；只读事件，不发消息。"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable

from launch import C, logger
from launch.adapter.websocket import (
    WebSocketClosed,
    WebSocketConnection,
    WebSocketProtocolError,
)

from .contracts import RouteEvent


class NapcatWebSocketClient:
    def __init__(
        self,
        *,
        url: str,
        token: str,
        on_event: Callable[[RouteEvent], None],
    ) -> None:
        self.url = url
        self.token = token
        self.on_event = on_event
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}

    async def run(self) -> None:
        delay = 3.0
        while True:
            try:
                connection = await WebSocketConnection.connect(
                    self.url, headers=self._headers, connect_timeout=10
                )
                logger.opt(colors=True).success(
                    C.join(
                        C.ok("辅助路由已连接 NapCat"),
                        C.kv("url", self.url),
                    )
                )
                delay = 3.0
                try:
                    while True:
                        kind, payload = await connection.receive()
                        if kind != "text":
                            continue
                        self._consume(str(payload))
                finally:
                    await connection.close()
            except asyncio.CancelledError:
                raise
            except (WebSocketClosed, WebSocketProtocolError, OSError) as exc:
                logger.opt(colors=True).warning(
                    C.join(
                        C.warn("辅助路由 NapCat 连接断开"),
                        C.kv("error", exc),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - 单条连接异常不能杀死重连
                logger.opt(colors=True).exception(
                    C.join(
                        C.warn("辅助路由 NapCat 处理异常"),
                        C.kv("error", exc),
                    )
                )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)

    def _consume(self, raw_text: str) -> None:
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            logger.opt(colors=True).warning(
                C.join(C.warn("辅助路由收到非 JSON WebSocket 帧"))
            )
            return
        if not isinstance(payload, dict) or payload.get("post_type") != "message":
            return
        message_type = str(payload.get("message_type") or "")
        if message_type not in {"private", "group"}:
            return
        sender = payload.get("sender") if isinstance(payload.get("sender"), dict) else {}
        user_id = str(payload.get("user_id") or sender.get("user_id") or "").strip()
        if not user_id:
            return
        text = str(payload.get("raw_message") or "").strip()
        if not text:
            message = payload.get("message")
            if isinstance(message, list):
                text = "".join(
                    str(part.get("data", {}).get("text") or "")
                    for part in message
                    if isinstance(part, dict) and part.get("type") == "text"
                ).strip()
        if not text:
            return
        group_id = str(payload.get("group_id") or "").strip()
        occurred_at = float(payload.get("time") or time.time())
        self.on_event(
            RouteEvent(
                source="napcat",
                bot_key=str(payload.get("self_id") or ""),
                scene="group" if group_id else "private",
                chat_id=group_id or user_id,
                sender_id=user_id,
                sender_name=str(sender.get("card") or sender.get("nickname") or ""),
                message_id=str(payload.get("message_id") or ""),
                occurred_at=occurred_at,
                text=text,
                raw=payload,
            )
        )
