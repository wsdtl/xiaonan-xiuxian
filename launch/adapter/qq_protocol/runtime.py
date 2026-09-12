"""QQ 驱动器的后台队列、用户顺序和按钮确认运行时。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from launch.log import C, logger
from launch.message_events import emit_message_event, event_from_incoming

from .client import client
from .dedupe import QqEventDeduplicator
from .event import QqMessageEvent

EventProcessor = Callable[[QqMessageEvent], Awaitable[bool]]
EventLogParts = Callable[[QqMessageEvent, bool], list[str]]
ShortId = Callable[[object], str]


@dataclass(frozen=True)
class QqRuntimeSettings:
    event_workers: int = 32
    max_waiting_events: int = 1000
    user_max_waiting_events: int = 5
    event_task_timeout: float = 9.0
    event_id_ttl_seconds: float = 120.0
    max_seen_event_ids: int = 3000
    interaction_ack_workers: int = 4
    max_waiting_interactions: int = 1000
    shutdown_drain_seconds: float = 3.0


class QqDriverRuntime:
    """只管理 QQ 驱动器自己的排队、去重和并发状态。"""

    def __init__(self, settings: QqRuntimeSettings | None = None) -> None:
        self.settings = settings or QqRuntimeSettings()
        self._deduplicator = QqEventDeduplicator(
            ttl_seconds=self.settings.event_id_ttl_seconds,
            max_entries=self.settings.max_seen_event_ids,
        )
        self._event_queue: asyncio.Queue[QqMessageEvent] | None = None
        self._event_workers: set[asyncio.Task] = set()
        self._interaction_queue: asyncio.Queue[str] | None = None
        self._interaction_workers: set[asyncio.Task] = set()
        self._interaction_executor: ThreadPoolExecutor | None = None
        self._waiting_events = 0
        self._waiting_guard = asyncio.Lock()
        self._user_locks: dict[str, asyncio.Lock] = {}
        self._user_counts: dict[str, int] = {}
        self._user_guard = asyncio.Lock()
        self._process_event: EventProcessor | None = None
        self._event_log_parts: EventLogParts | None = None
        self._short_id: ShortId | None = None

    async def start(
        self,
        *,
        process_event: EventProcessor,
        event_log_parts: EventLogParts,
        short_id: ShortId,
    ) -> None:
        """启动固定 worker；重复调用不会创建第二套队列。"""

        self._process_event = process_event
        self._event_log_parts = event_log_parts
        self._short_id = short_id

        if not self._event_workers:
            self._event_queue = asyncio.Queue(maxsize=self.settings.max_waiting_events)
            for index in range(self.settings.event_workers):
                task = asyncio.create_task(
                    self._event_worker(index), name=f"qq-event-worker-{index}"
                )
                self._event_workers.add(task)
                task.add_done_callback(self._event_workers.discard)

        if not self._interaction_workers:
            self._interaction_executor = ThreadPoolExecutor(
                max_workers=self.settings.interaction_ack_workers,
                thread_name_prefix="qq-ack",
            )
            self._interaction_queue = asyncio.Queue(
                maxsize=self.settings.max_waiting_interactions
            )
            for index in range(self.settings.interaction_ack_workers):
                task = asyncio.create_task(
                    self._interaction_worker(index),
                    name=f"qq-interaction-ack-worker-{index}",
                )
                self._interaction_workers.add(task)
                task.add_done_callback(self._interaction_workers.discard)

    async def shutdown(self) -> None:
        """短暂排空并关闭 QQ 自己的全部后台资源。"""

        await self._drain_event_queue()
        await self._drain_interaction_queue()
        await _cancel_tasks(self._event_workers)
        await _cancel_tasks(self._interaction_workers)
        self._event_queue = None
        self._interaction_queue = None
        self._shutdown_interaction_executor()
        await self._deduplicator.clear()
        async with self._user_guard:
            self._user_locks.clear()
            self._user_counts.clear()
        self._waiting_events = 0
        self._process_event = None
        self._event_log_parts = None
        self._short_id = None

    async def enqueue_event(self, event: QqMessageEvent) -> None:
        """非阻塞地把已经解析的 QQ 事件送入后台队列。"""

        queue = self._event_queue
        if queue is None:
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ 事件队列未启动"),
                    *self._log_parts(event, include_message=False),
                )
            )
            return

        if not await self._reserve_user_event(event.user_id):
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ 单用户事件排队已满"),
                    *self._log_parts(event, include_message=False),
                    C.kv("max_waiting", self.settings.user_max_waiting_events),
                )
            )
            return

        if not await self._reserve_waiting_event():
            await self._release_user_event(event.user_id)
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ webhook 后台队列已满"),
                    C.kv("max_waiting", self.settings.max_waiting_events),
                )
            )
            return

        if not await self._deduplicator.remember_once(event):
            await self._release_waiting_event()
            await self._release_user_event(event.user_id)
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ 重复事件已跳过"),
                    *self._log_parts(event, include_message=False),
                )
            )
            return

        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            await self._deduplicator.forget(event)
            await self._release_waiting_event()
            await self._release_user_event(event.user_id)
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ webhook 后台队列已满"),
                    C.kv("max_waiting", self.settings.max_waiting_events),
                )
            )
            return

        emit_message_event(
            event_from_incoming(
                adapter="qq",
                user_id=event.user_id,
                request_id=event.event_id or event.message_id,
                message_type="text",
                content=event.content,
                sender_name=event.sender_name,
            )
        )

    def enqueue_interaction_ack(self, event: QqMessageEvent) -> None:
        """在 webhook 热路径中只做按钮 ACK 非阻塞入队。"""

        if not event.interaction_id or self._interaction_queue is None:
            return
        try:
            self._interaction_queue.put_nowait(event.interaction_id)
        except asyncio.QueueFull:
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ 按钮 ACK 队列已满"),
                    C.kv("interaction", self._format_short_id(event.interaction_id)),
                    C.kv("max_waiting", self.settings.max_waiting_interactions),
                )
            )

    async def _event_worker(self, index: int) -> None:
        queue = self._event_queue
        if queue is None:
            return
        try:
            while True:
                event = await queue.get()
                try:
                    await self._run_event_task(event)
                except Exception as exc:  # noqa: BLE001 - 单个事件不能终止 worker
                    logger.opt(colors=True, exception=exc).error(
                        C.join(
                            C.fail("QQ 事件 worker 异常"),
                            C.kv("worker", index),
                            *self._log_parts(event, include_message=False),
                        )
                    )
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            return

    async def _interaction_worker(self, index: int) -> None:
        queue = self._interaction_queue
        if queue is None:
            return
        try:
            while True:
                interaction_id = await queue.get()
                try:
                    await self._ack_interaction(interaction_id)
                except Exception as exc:  # noqa: BLE001 - 单个 ACK 不能终止 worker
                    logger.opt(colors=True, exception=exc).warning(
                        C.join(
                            C.warn("QQ 按钮 ACK worker 异常"),
                            C.kv("worker", index),
                            C.kv("interaction", self._format_short_id(interaction_id)),
                        )
                    )
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            return

    async def _run_event_task(self, event: QqMessageEvent) -> None:
        async def run_with_limits() -> bool:
            user_lock = await self._user_lock(event.user_id)
            async with user_lock:
                if self._process_event is None:
                    raise RuntimeError("QQ 事件处理器尚未绑定")
                return await self._process_event(event)

        try:
            await asyncio.wait_for(
                run_with_limits(), timeout=self.settings.event_task_timeout
            )
        except asyncio.TimeoutError:
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ 事件处理超时，已终止"),
                    *self._log_parts(event, include_message=False),
                    C.kv("timeout", self.settings.event_task_timeout),
                )
            )
        finally:
            await self._release_waiting_event()
            await self._release_user_event(event.user_id)

    async def _ack_interaction(self, interaction_id: str) -> None:
        try:
            executor = self._interaction_executor
            if executor is None:
                raise RuntimeError("QQ 按钮 ACK 线程池未启动")
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(executor, client.ack_interaction, interaction_id)
        except Exception as exc:  # noqa: BLE001 - ACK 是独立的尽力而为边界
            logger.opt(colors=True, exception=exc).warning(
                C.join(
                    C.warn("QQ 按钮回调确认失败"),
                    C.kv("interaction", self._format_short_id(interaction_id)),
                )
            )

    async def _drain_event_queue(self) -> None:
        queue = self._event_queue
        if queue is None:
            return
        try:
            await asyncio.wait_for(
                queue.join(), timeout=self.settings.shutdown_drain_seconds
            )
        except asyncio.TimeoutError:
            dropped = await self._drop_waiting_events(queue)
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ 事件队列关闭等待超时"),
                    C.kv("dropped", dropped),
                    C.kv("waiting", queue.qsize()),
                )
            )

    async def _drain_interaction_queue(self) -> None:
        queue = self._interaction_queue
        if queue is None:
            return
        try:
            await asyncio.wait_for(
                queue.join(), timeout=self.settings.shutdown_drain_seconds
            )
        except asyncio.TimeoutError:
            dropped = _drop_waiting_interactions(queue)
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ 按钮 ACK 队列关闭等待超时"),
                    C.kv("dropped", dropped),
                    C.kv("waiting", queue.qsize()),
                )
            )

    async def _drop_waiting_events(self, queue: asyncio.Queue[QqMessageEvent]) -> int:
        dropped = 0
        while True:
            try:
                event = queue.get_nowait()
            except asyncio.QueueEmpty:
                return dropped
            await self._release_waiting_event()
            await self._release_user_event(event.user_id)
            queue.task_done()
            dropped += 1

    async def _reserve_waiting_event(self) -> bool:
        async with self._waiting_guard:
            if self._waiting_events >= self.settings.max_waiting_events:
                return False
            self._waiting_events += 1
            return True

    async def _release_waiting_event(self) -> None:
        async with self._waiting_guard:
            if self._waiting_events > 0:
                self._waiting_events -= 1

    async def _reserve_user_event(self, user_id: str) -> bool:
        async with self._user_guard:
            count = self._user_counts.get(user_id, 0)
            if count >= self.settings.user_max_waiting_events:
                return False
            self._user_counts[user_id] = count + 1
            self._user_locks.setdefault(user_id, asyncio.Lock())
            return True

    async def _release_user_event(self, user_id: str) -> None:
        async with self._user_guard:
            count = self._user_counts.get(user_id, 0) - 1
            if count > 0:
                self._user_counts[user_id] = count
                return
            self._user_counts.pop(user_id, None)
            self._user_locks.pop(user_id, None)

    async def _user_lock(self, user_id: str) -> asyncio.Lock:
        async with self._user_guard:
            return self._user_locks.setdefault(user_id, asyncio.Lock())

    def _shutdown_interaction_executor(self) -> None:
        executor = self._interaction_executor
        self._interaction_executor = None
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    def _log_parts(self, event: QqMessageEvent, *, include_message: bool) -> list[str]:
        if self._event_log_parts is None:
            return []
        return self._event_log_parts(event, include_message)

    def _format_short_id(self, value: object) -> str:
        if self._short_id is None:
            return str(value or "-")
        return self._short_id(value)


async def _cancel_tasks(tasks: set[asyncio.Task]) -> None:
    running = list(tasks)
    for task in running:
        task.cancel()
    if running:
        await asyncio.gather(*running, return_exceptions=True)
    tasks.clear()


def _drop_waiting_interactions(queue: asyncio.Queue[str]) -> int:
    dropped = 0
    while True:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            return dropped
        queue.task_done()
        dropped += 1


__all__ = ["QqDriverRuntime", "QqRuntimeSettings"]
