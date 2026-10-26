"""辅助路由服务：框架官方事件 + NapCat 事件，用户/群自动分域。"""

from __future__ import annotations

import asyncio
from dataclasses import replace

from launch import C, logger
from launch.message_events import (
    MessageEvent,
    subscribe_message_events,
    unsubscribe_message_events,
)

from .config import (
    AUTO_CONFIRM_GROUP,
    AUTO_CONFIRM_USER,
    CONFIRM_SCORE,
    EVENT_RETENTION_SECONDS,
    MATCH_WINDOW_SECONDS,
    MAX_EVENTS,
    AssistRouterSettings,
)
from .contracts import RouteEvent
from .matcher import match_group, match_user, normalize_text
from .napcat_ws import NapcatWebSocketClient
from .store import AssistRouterStore


_QUEUE_MAX = 10000


class AssistRouterService:
    def __init__(self, settings: AssistRouterSettings | None = None) -> None:
        self.settings = settings or AssistRouterSettings()
        self.store = AssistRouterStore(
            self.settings.db_path,
            max_events=MAX_EVENTS,
            retention_seconds=EVENT_RETENTION_SECONDS,
        )
        self._queue: asyncio.Queue[RouteEvent | None] | None = None
        self._worker: asyncio.Task | None = None
        self._napcat_task: asyncio.Task | None = None
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    def start(self) -> None:
        if self._started:
            return
        self.store.open()
        self._queue = asyncio.Queue(maxsize=_QUEUE_MAX)
        self._worker = asyncio.create_task(self._run_worker(), name="assist-router-worker")
        subscribe_message_events(self.on_framework_message)
        self._started = True
        if self.settings.napcat_url:
            client = NapcatWebSocketClient(
                url=self.settings.napcat_url,
                token=self.settings.napcat_token,
                on_event=self.on_napcat_event,
            )
            self._napcat_task = asyncio.create_task(
                client.run(), name="assist-router-napcat"
            )

    async def stop(self) -> None:
        if not self._started:
            return
        unsubscribe_message_events(self.on_framework_message)
        if self._napcat_task is not None:
            self._napcat_task.cancel()
            try:
                await self._napcat_task
            except asyncio.CancelledError:
                pass
            self._napcat_task = None
        if self._worker is not None and self._queue is not None:
            try:
                self._queue.put_nowait(None)
                await asyncio.wait_for(self._worker, timeout=5)
            except (asyncio.QueueFull, asyncio.TimeoutError):
                self._worker.cancel()
                try:
                    await self._worker
                except asyncio.CancelledError:
                    pass
            self._worker = None
        self._queue = None
        self.store.close()
        self._started = False

    def on_framework_message(self, event: MessageEvent) -> None:
        if event.direction != "incoming" or event.adapter != "qq":
            return
        self._enqueue(
            RouteEvent(
                source="qq",
                bot_key=event.bot_key or "qq",
                scene="group" if event.group_id else "private",
                chat_id=event.group_id or event.user_id,
                sender_id=event.user_id,
                sender_name=event.sender_name,
                message_id=event.message_id,
                occurred_at=event.occurred_at,
                text=normalize_text(event.content),
                raw={},
            )
        )

    def on_napcat_event(self, event: RouteEvent) -> None:
        self._enqueue(event)

    def _enqueue(self, event: RouteEvent) -> None:
        queue = self._queue
        if queue is None:
            return
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.opt(colors=True).warning(
                C.join(C.warn("辅助路由事件队列已满，丢弃一条事件"))
            )

    async def _run_worker(self) -> None:
        queue = self._queue
        if queue is None:
            return
        while True:
            event = await queue.get()
            try:
                if event is None:
                    return
                await asyncio.to_thread(self._ingest, event)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - 单条事件失败不能杀死工作线程
                logger.opt(colors=True).exception(
                    C.join(C.warn("辅助路由处理事件失败"))
                )
            finally:
                queue.task_done()

    def _ingest(self, event: RouteEvent) -> None:
        if not event.sender_id or not event.text:
            return
        text = normalize_text(event.text)
        if text != event.text:
            event = replace(event, text=text)
        event_id = self.store.insert_event(event)

        if event.scene == "group":
            match_group(
                event,
                event_id,
                self.store,
                window=MATCH_WINDOW_SECONDS,
                confirm_score=CONFIRM_SCORE,
                auto_confirm=AUTO_CONFIRM_GROUP,
            )
        match_user(
            event,
            event_id,
            self.store,
            window=MATCH_WINDOW_SECONDS,
            confirm_score=CONFIRM_SCORE,
            auto_confirm=AUTO_CONFIRM_USER,
        )

    def resolve_user(self, *, bot_key: str, openid: str) -> dict | None:
        return self.store.resolve_user(official_bot_key=bot_key, openid=openid)

    def resolve_group(self, *, bot_key: str, group_openid: str) -> dict | None:
        return self.store.resolve_group(
            official_bot_key=bot_key, group_openid=group_openid
        )

    def stats(self) -> dict:
        result = {
            "started": self._started,
            "napcat_configured": bool(self.settings.napcat_url),
        }
        try:
            result.update(self.store.stats())
        except Exception as exc:  # noqa: BLE001 - 数据库未就绪时健康检查仍要可读
            result["error"] = str(exc)
        return result
