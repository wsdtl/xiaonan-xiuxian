"""QQ 事件重试与重复投递去重。"""

from __future__ import annotations

import asyncio
from collections import deque
from time import monotonic

from .event import QqMessageEvent


class QqEventDeduplicator:
    """维护 QQ 驱动器进程内的短期事件声明。"""

    def __init__(self, *, ttl_seconds: float, max_entries: int) -> None:
        self._ttl_seconds = float(ttl_seconds)
        self._max_entries = int(max_entries)
        self._timestamps: dict[str, float] = {}
        self._order: deque[tuple[float, str]] = deque()
        self._guard = asyncio.Lock()

    async def remember_once(self, event: QqMessageEvent) -> bool:
        """声明事件；已经存在时返回 False。"""

        event_key = event_dedupe_key(event)
        if not event_key:
            return True

        now_value = monotonic()
        async with self._guard:
            self._clear_expired(now_value)
            if event_key in self._timestamps:
                return False
            self._timestamps[event_key] = now_value
            self._order.append((now_value, event_key))
            self._trim()
            return True

    async def forget(self, event: QqMessageEvent) -> None:
        """撤销尚未成功入队的事件声明。"""

        event_key = event_dedupe_key(event)
        if not event_key:
            return
        async with self._guard:
            self._timestamps.pop(event_key, None)

    async def clear(self) -> None:
        async with self._guard:
            self._timestamps.clear()
            self._order.clear()

    def _clear_expired(self, now_value: float) -> None:
        expires_before = now_value - self._ttl_seconds
        while self._order and self._order[0][0] <= expires_before:
            created_at, event_key = self._order.popleft()
            if self._timestamps.get(event_key) == created_at:
                self._timestamps.pop(event_key, None)

    def _trim(self) -> None:
        while len(self._order) > self._max_entries:
            created_at, event_key = self._order.popleft()
            if self._timestamps.get(event_key) == created_at:
                self._timestamps.pop(event_key, None)


def event_dedupe_key(event: QqMessageEvent) -> str:
    """普通消息按消息 ID，按钮按交互 ID 去重。"""

    if event.interaction_id:
        raw_key = event.interaction_id or event.event_id
        key_type = "interaction"
    else:
        raw_key = event.message_id or event.event_id
        key_type = "message"
    return f"{key_type}:{raw_key}" if raw_key else ""


__all__ = ["QqEventDeduplicator", "event_dedupe_key"]
