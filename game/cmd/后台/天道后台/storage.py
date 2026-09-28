"""天道后台使用的短期消息流水 SQLite 仓储。"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock


@dataclass(frozen=True)
class MessageFlowRow:
    """持久化层返回的原始消息流水行。"""

    flow_id: int
    direction: str
    adapter: str
    request_id: str
    user_id: str
    sender_name: str
    message_type: str
    content: str
    image: str
    interactions_json: str
    content_truncated: bool
    created_at: str
    created_at_timestamp: float
    expires_at: float


class MessageFlowStore:
    """只负责短期消息表和分页查询，不解释消息及交互语义。"""

    def __init__(
        self,
        path: Path | str,
        *,
        retention_seconds: int,
        busy_timeout_ms: int = 5000,
    ) -> None:
        self.path = Path(path)
        self.retention_seconds = max(60, int(retention_seconds))
        self.busy_timeout_ms = max(1, int(busy_timeout_ms))
        self._lock = RLock()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            tables = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1"
            ).fetchone()
            if tables is None:
                connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
                connection.execute("VACUUM")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS log_message_flows (
                    flow_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    direction TEXT NOT NULL,
                    adapter TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    sender_name TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    image TEXT NOT NULL,
                    interactions_json TEXT NOT NULL,
                    content_truncated INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    created_at_timestamp REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_log_message_flows_created
                ON log_message_flows(created_at_timestamp);
                CREATE INDEX IF NOT EXISTS ix_log_message_flows_expires
                ON log_message_flows(expires_at);
                """
            )

    def insert(
        self,
        *,
        direction: str,
        adapter: str,
        request_id: str,
        user_id: str,
        sender_name: str,
        message_type: str,
        content: str,
        image: str,
        interactions_json: str,
        content_truncated: bool,
        created_at: str,
        created_at_timestamp: float,
    ) -> MessageFlowRow:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO log_message_flows (
                    direction, adapter, request_id, user_id, sender_name,
                    message_type, content, image, interactions_json,
                    content_truncated, created_at, created_at_timestamp, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    direction,
                    adapter,
                    request_id,
                    user_id,
                    sender_name,
                    message_type,
                    content,
                    image,
                    interactions_json,
                    int(content_truncated),
                    created_at,
                    created_at_timestamp,
                    float(created_at_timestamp) + self.retention_seconds,
                ),
            )
            row = connection.execute(
                "SELECT * FROM log_message_flows WHERE flow_id = ?",
                (int(cursor.lastrowid),),
            ).fetchone()
        if row is None:
            raise RuntimeError("消息流水写入后无法读取")
        return _row(row)

    def recent(
        self, *, limit: int, before_id: int | None = None
    ) -> list[MessageFlowRow]:
        count = max(1, int(limit))
        query = "SELECT * FROM log_message_flows WHERE expires_at > ?"
        parameters: list[object] = [time.time()]
        if before_id is not None and before_id > 0:
            query += " AND flow_id < ?"
            parameters.append(before_id)
        query += " ORDER BY flow_id DESC LIMIT ?"
        parameters.append(count)
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return list(reversed([_row(row) for row in rows]))

    def after(self, flow_id: int, *, limit: int) -> list[MessageFlowRow]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM log_message_flows
                WHERE flow_id > ? AND expires_at > ?
                ORDER BY flow_id ASC
                LIMIT ?
                """,
                (max(0, int(flow_id)), time.time(), max(1, int(limit))),
            ).fetchall()
        return [_row(row) for row in rows]

    def get(self, flow_id: int) -> MessageFlowRow | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM log_message_flows WHERE flow_id = ? AND expires_at > ?",
                (int(flow_id), time.time()),
            ).fetchone()
        return _row(row) if row is not None else None

    def cleanup(self, *, now_timestamp: float, max_rows: int) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM log_message_flows WHERE expires_at <= ?",
                (float(now_timestamp),),
            )
            connection.execute(
                """
                DELETE FROM log_message_flows
                WHERE flow_id NOT IN (
                    SELECT flow_id FROM log_message_flows
                    ORDER BY flow_id DESC LIMIT ?
                )
                """,
                (max(1, int(max_rows)),),
            )
            connection.execute("PRAGMA optimize")
            if int(connection.execute("PRAGMA auto_vacuum").fetchone()[0]) == 2:
                connection.execute("PRAGMA incremental_vacuum(128)")

    def referenced_images(self) -> set[str]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT image FROM log_message_flows WHERE image <> '' AND expires_at > ?",
                (time.time(),),
            ).fetchall()
        return {str(row["image"]) for row in rows}

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1000,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            with connection:
                yield connection
        finally:
            connection.close()


def _row(row: sqlite3.Row | tuple[object, ...]) -> MessageFlowRow:
    return MessageFlowRow(
        flow_id=int(row["flow_id"]),
        direction=str(row["direction"]),
        adapter=str(row["adapter"]),
        request_id=str(row["request_id"]),
        user_id=str(row["user_id"]),
        sender_name=str(row["sender_name"]),
        message_type=str(row["message_type"]),
        content=str(row["content"]),
        image=str(row["image"]),
        interactions_json=str(row["interactions_json"]),
        content_truncated=bool(row["content_truncated"]),
        created_at=str(row["created_at"]),
        created_at_timestamp=float(row["created_at_timestamp"]),
        expires_at=float(row["expires_at"]),
    )


__all__ = ["MessageFlowRow", "MessageFlowStore"]
