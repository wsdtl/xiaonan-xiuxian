"""天道后台消息观察、短期存储和本地驱动执行服务。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from game.config import game_config
from launch import C, config, logger
from launch.adapter import dispatch_local_message
from launch.message_events import (
    MessageEvent,
    MessageInteraction,
    emit_message_event,
    event_from_outgoing,
)
from launch.paths import STATIC_DIR, static_url
from message import Action, M

from .auth import ConsoleAuthService
from .models import ConsoleFlowRecord
from .storage import MessageFlowStore

CONSOLE_USER_ID = "system.heavenly_dao"
CONSOLE_SENDER_NAME = "天道"
SESSION_COOKIE_NAME = "xiaonan_console_session"
MAX_COMMAND_LENGTH = 4000
MEMORY_RECORD_LIMIT = 300
EVENT_QUEUE_LIMIT = 5000
SUBSCRIBER_QUEUE_LIMIT = 500
MEDIA_MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 1_000
RETENTION_SECONDS = 2 * 60 * 60
MAX_CONTENT_BYTES = 256 * 1024


class MessageFlowStorage(Protocol):
    """Web 组件需要的最小短期消息仓储能力。"""

    def initialize(self) -> None: ...
    def insert(self, **values): ...
    def recent(self, *, limit: int, before_id: int | None = None) -> list: ...
    def after(self, flow_id: int, *, limit: int) -> list: ...
    def get(self, flow_id: int): ...
    def cleanup(self, *, now_timestamp: float, max_rows: int) -> None: ...
    def referenced_images(self) -> set[str]: ...


@dataclass(frozen=True)
class InteractionResult:
    """网页交互的前端处理结果。"""

    kind: str
    value: str = ""
    matched: bool = False


class MessageConsoleService:
    """串行记录双驱动消息，并以固定本地身份执行网页操作。"""

    def __init__(
        self,
        storage: MessageFlowStorage,
        *,
        media_dir: Path,
    ) -> None:
        self.storage = storage
        self.auth = ConsoleAuthService()
        self.media_dir = Path(media_dir)
        self._event_queue: asyncio.Queue[MessageEvent | None] = asyncio.Queue(
            EVENT_QUEUE_LIMIT
        )
        self._worker: asyncio.Task | None = None
        self._records: deque[ConsoleFlowRecord] = deque(maxlen=MEMORY_RECORD_LIMIT)
        self._subscribers: set[asyncio.Queue[ConsoleFlowRecord | None]] = set()
        self._subscriber_lock = asyncio.Lock()
        self._record_count = 0

    async def start(self) -> None:
        if self._worker is not None:
            return
        self.storage.initialize()
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self._records.clear()
        self._records.extend(
            _record_from_row(row)
            for row in self.storage.recent(limit=MEMORY_RECORD_LIMIT)
        )
        self._cleanup_media()
        self._worker = asyncio.create_task(
            self._run(), name="heavenly-dao-message-writer"
        )

    async def shutdown(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            await self._event_queue.put(None)
            await worker
        async with self._subscriber_lock:
            subscribers = tuple(self._subscribers)
            self._subscribers.clear()
        for queue in subscribers:
            _replace_queue_tail(queue, None)

    def handle_event(self, event: MessageEvent) -> None:
        """同步订阅入口只排队，避免拖慢任何真实驱动器。"""

        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                self._event_queue.get_nowait()
                self._event_queue.task_done()
                self._event_queue.put_nowait(event)
            except asyncio.QueueEmpty:
                pass
            logger.opt(colors=True).warning(
                C.warn("天道后台消息队列已满，已淘汰最旧待写事件")
            )

    def recent(
        self, *, limit: int = 50, before_id: int | None = None
    ) -> list[ConsoleFlowRecord]:
        count = max(1, min(int(limit), 50))
        return [
            _record_from_row(row)
            for row in self.storage.recent(limit=count, before_id=before_id)
        ]

    async def subscribe(
        self, *, after_id: int = 0
    ) -> asyncio.Queue[ConsoleFlowRecord | None]:
        queue: asyncio.Queue[ConsoleFlowRecord | None] = asyncio.Queue(
            SUBSCRIBER_QUEUE_LIMIT
        )
        async with self._subscriber_lock:
            self._subscribers.add(queue)
        for row in self.storage.after(after_id, limit=SUBSCRIBER_QUEUE_LIMIT):
            record = _record_from_row(row)
            _replace_queue_tail(queue, record)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[ConsoleFlowRecord | None]) -> None:
        async with self._subscriber_lock:
            self._subscribers.discard(queue)

    async def flush(self) -> None:
        """等待已观察到的消息全部写入，供关闭流程和测试使用。"""

        await self._event_queue.join()

    async def dispatch(self, command: str):
        normalized = str(command or "").strip()
        if not normalized:
            raise ValueError("命令不能为空")
        if len(normalized) > MAX_COMMAND_LENGTH:
            raise ValueError(f"命令不能超过 {MAX_COMMAND_LENGTH} 个字符")
        result = await dispatch_local_message(
            user_id=CONSOLE_USER_ID,
            raw_message=normalized,
            sender_name=CONSOLE_SENDER_NAME,
        )
        if not result.matched:
            emit_message_event(
                event_from_outgoing(
                    adapter="local",
                    user_id=CONSOLE_USER_ID,
                    request_id=result.event.event_id,
                    message=(
                        M.document()
                        .section("命令状态", icon="notice")
                        .line(
                            M.status("未识别", tone="warning"),
                            " 检查输入，或从帮助中选择可用命令。",
                        )
                        .action(
                            Action(
                                "heavenly_dao.unmatched.help",
                                "查看帮助",
                                "帮助",
                            )
                        )
                        .build()
                    ),
                )
            )
        return result

    async def execute_action(self, flow_id: int, action_id: str) -> InteractionResult:
        row = self.storage.get(flow_id)
        if row is None:
            raise LookupError("消息不存在或已经过期")
        record = _record_from_row(row)
        interaction = next(
            (
                item
                for item in record.interactions
                if item.action_id == str(action_id or "")
            ),
            None,
        )
        if interaction is None:
            raise LookupError("消息交互不存在")
        self._assert_interaction_permission(interaction)
        if interaction.behavior == "link":
            return InteractionResult("link", interaction.data)
        if interaction.behavior == "fill" or not interaction.submit:
            return InteractionResult("fill", interaction.data)
        result = await self.dispatch(interaction.data)
        return InteractionResult("dispatch", interaction.data, result.matched)

    def media_path(self, name: str) -> Path | None:
        safe_name = Path(str(name or "")).name
        if not safe_name or safe_name != str(name or ""):
            return None
        path = (self.media_dir / safe_name).resolve()
        if path.parent != self.media_dir.resolve() or not path.is_file():
            return None
        return path

    async def _run(self) -> None:
        while True:
            event = await self._event_queue.get()
            try:
                if event is None:
                    return
                record = self._record(event)
                self._records.append(record)
                await self._publish(record)
            except Exception as exc:  # noqa: BLE001 - 消息观察器不能因单条记录停止
                logger.opt(colors=True, exception=exc).warning(
                    C.warn("天道后台消息写入失败")
                )
            finally:
                self._event_queue.task_done()

    def _record(self, event: MessageEvent) -> ConsoleFlowRecord:
        now_value = datetime.now(ZoneInfo(config.project.timezone))
        image = self._materialize_image(event.image)
        content, truncated = _bounded_text(event.content, MAX_CONTENT_BYTES)
        sender_name = event.sender_name.strip()
        if not sender_name:
            sender_name = (
                "晓楠修仙"
                if event.direction == "outgoing"
                else event.user_id or "未知用户"
            )
        normalized = MessageEvent(
            direction=event.direction,
            adapter=event.adapter,
            request_id=event.request_id,
            user_id=event.user_id,
            message_type=event.message_type,
            content=content,
            sender_name=sender_name,
            image=image,
            interactions=event.interactions,
        )
        row = self.storage.insert(
            direction=normalized.direction,
            adapter=normalized.adapter,
            request_id=normalized.request_id,
            user_id=normalized.user_id,
            sender_name=normalized.sender_name,
            message_type=normalized.message_type,
            content=normalized.content,
            image=image,
            interactions_json=json.dumps(
                [asdict(interaction) for interaction in normalized.interactions],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            content_truncated=truncated,
            created_at=now_value.isoformat(timespec="seconds"),
            created_at_timestamp=time.time(),
        )
        record = _record_from_row(row)
        self._record_count += 1
        return record

    def cleanup(self) -> None:
        """供唯一的运行日志定时任务调用。"""

        self.storage.initialize()
        self.storage.cleanup(now_timestamp=time.time(), max_rows=MAX_ROWS)
        self._cleanup_media()

    async def _publish(self, record: ConsoleFlowRecord) -> None:
        async with self._subscriber_lock:
            subscribers = tuple(self._subscribers)
        for queue in subscribers:
            _replace_queue_tail(queue, record)

    def _materialize_image(self, image: object) -> str:
        if image is None:
            return ""
        if isinstance(image, Path):
            return self._path_image(image)
        if isinstance(image, str):
            text = image.strip()
            if not text or text == "〔图片〕":
                return text
            if text.startswith(("http://", "https://", "/")):
                return text
            path = Path(text)
            return self._path_image(path) if path.is_file() else "〔图片〕"
        if isinstance(image, BytesIO):
            return self._bytes_image(image.getvalue())
        if isinstance(image, (bytes, bytearray, memoryview)):
            return self._bytes_image(bytes(image))
        return "〔图片〕"

    def _path_image(self, path: Path) -> str:
        try:
            resolved = path.resolve()
            relative = resolved.relative_to(STATIC_DIR.resolve())
            return static_url(*relative.parts)
        except (OSError, ValueError):
            pass
        try:
            return self._bytes_image(path.read_bytes(), suffix=path.suffix)
        except OSError:
            return "〔图片〕"

    def _bytes_image(self, value: bytes, *, suffix: str = "") -> str:
        if not value or len(value) > MEDIA_MAX_BYTES:
            return "〔图片内容为空或超过 10 MiB〕"
        extension = (
            suffix.lower()
            if suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
            else _image_suffix(value)
        )
        digest = hashlib.sha256(value).hexdigest()
        filename = f"{digest}{extension}"
        path = self.media_dir / filename
        if not path.exists():
            path.write_bytes(value)
        return f"/game-console/media/{filename}"

    def _cleanup_media(self) -> None:
        references = {
            Path(value).name
            for value in self.storage.referenced_images()
            if value.startswith("/game-console/media/")
        }
        if not self.media_dir.exists():
            return
        for path in self.media_dir.iterdir():
            if path.is_file() and path.name not in references:
                try:
                    path.unlink()
                except OSError:
                    continue

    @staticmethod
    def _assert_interaction_permission(interaction: MessageInteraction) -> None:
        if interaction.permission in {"everyone", "admins"}:
            return
        if (
            interaction.permission == "specified"
            and CONSOLE_USER_ID in interaction.specified_user_ids
        ):
            return
        raise PermissionError("该交互不允许天道身份执行")


def _replace_queue_tail(queue: asyncio.Queue, value: Any) -> None:
    if queue.full():
        try:
            queue.get_nowait()
            queue.task_done()
        except asyncio.QueueEmpty:
            pass
    queue.put_nowait(value)


def _image_suffix(value: bytes) -> str:
    signatures = (
        (b"\x89PNG\r\n\x1a\n", ".png"),
        (b"\xff\xd8\xff", ".jpg"),
        (b"GIF87a", ".gif"),
        (b"GIF89a", ".gif"),
        (b"RIFF", ".webp"),
    )
    for signature, suffix in signatures:
        if value.startswith(signature):
            return suffix
    guessed = mimetypes.guess_extension("application/octet-stream")
    return guessed or ".bin"


service = MessageConsoleService(
    MessageFlowStore(
        game_config.database.runtime_log_path,
        retention_seconds=RETENTION_SECONDS,
        busy_timeout_ms=game_config.database.busy_timeout_ms,
    ),
    media_dir=config.base_dir / ".runtime" / "runtime_log_media",
)


def _record_from_row(row) -> ConsoleFlowRecord:
    interactions: list[MessageInteraction] = []
    try:
        values = json.loads(str(row.interactions_json or "[]"))
    except json.JSONDecodeError:
        values = []
    for value in values:
        if not isinstance(value, dict):
            continue
        try:
            interactions.append(
                MessageInteraction(
                    kind=str(value.get("kind") or "action"),
                    action_id=str(value.get("action_id") or ""),
                    label=str(value.get("label") or ""),
                    data=str(value.get("data") or ""),
                    behavior=str(value.get("behavior") or "callback"),
                    style=str(value.get("style") or "primary"),
                    permission=str(value.get("permission") or "everyone"),
                    specified_user_ids=tuple(
                        str(item) for item in value.get("specified_user_ids", ())
                    ),
                    reply=bool(value.get("reply")),
                    submit=bool(value.get("submit", True)),
                )
            )
        except (TypeError, ValueError):
            continue
    return ConsoleFlowRecord(
        flow_id=int(row.flow_id),
        direction=str(row.direction),
        adapter=str(row.adapter),
        request_id=str(row.request_id),
        user_id=str(row.user_id),
        sender_name=str(row.sender_name),
        message_type=str(row.message_type),
        content=str(row.content),
        image=str(row.image),
        interactions=tuple(interactions),
        content_truncated=bool(row.content_truncated),
        created_at=str(row.created_at),
        created_at_timestamp=float(row.created_at_timestamp),
    )


def _bounded_text(value: object, maximum_bytes: int) -> tuple[str, bool]:
    text = str(value or "")
    encoded = text.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return text, False
    suffix = "\n\n[消息内容超过 256 KiB，流水仅保留可见前段。]"
    allowance = maximum_bytes - len(suffix.encode("utf-8"))
    prefix = encoded[:allowance].decode("utf-8", errors="ignore")
    return prefix + suffix, True


__all__ = [
    "CONSOLE_SENDER_NAME",
    "CONSOLE_USER_ID",
    "SESSION_COOKIE_NAME",
    "InteractionResult",
    "MessageConsoleService",
    "MessageFlowStorage",
    "service",
]
