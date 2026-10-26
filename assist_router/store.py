"""辅助路由的独立 SQLite：用户/群各一套身份别名，不存昵称。"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .contracts import RouteEvent


class AssistRouterStore:
    def __init__(
        self,
        path: Path,
        *,
        max_events: int = 20000,
        retention_seconds: int = 600,
    ) -> None:
        self.path = Path(path)
        self.max_events = max_events
        self.retention_seconds = retention_seconds
        self._lock = threading.Lock()
        self._connection: sqlite3.Connection | None = None

    def open(self) -> None:
        with self._lock:
            if self._connection is not None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    bot_key TEXT NOT NULL,
                    scene TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    sender_name TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    occurred_at REAL NOT NULL,
                    text TEXT NOT NULL,
                    user_consumed INTEGER NOT NULL DEFAULT 0,
                    group_consumed INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_user_lookup
                    ON events(source, scene, text, occurred_at, user_consumed);
                CREATE INDEX IF NOT EXISTS events_group_lookup
                    ON events(source, scene, text, occurred_at, group_consumed);
                CREATE UNIQUE INDEX IF NOT EXISTS events_message_unique
                    ON events(source, bot_key, message_id)
                    WHERE message_id <> '';

                CREATE TABLE IF NOT EXISTS users (
                    qq_uin TEXT PRIMARY KEY,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_aliases (
                    official_bot_key TEXT NOT NULL,
                    openid TEXT NOT NULL,
                    qq_uin TEXT NOT NULL,
                    scene TEXT NOT NULL DEFAULT '',
                    group_openid TEXT NOT NULL DEFAULT '',
                    confidence INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    evidence_json TEXT NOT NULL,
                    PRIMARY KEY (official_bot_key, openid)
                );
                CREATE INDEX IF NOT EXISTS user_aliases_uin
                    ON user_aliases(qq_uin);
                CREATE INDEX IF NOT EXISTS user_aliases_scope
                    ON user_aliases(qq_uin, scene, group_openid);

                CREATE TABLE IF NOT EXISTS groups (
                    qq_group_id TEXT PRIMARY KEY,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS group_aliases (
                    official_bot_key TEXT NOT NULL,
                    group_openid TEXT NOT NULL,
                    qq_group_id TEXT NOT NULL,
                    confidence INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    evidence_json TEXT NOT NULL,
                    PRIMARY KEY (official_bot_key, group_openid)
                );
                CREATE INDEX IF NOT EXISTS group_aliases_group
                    ON group_aliases(qq_group_id);

                """
            )
            self._connection = connection

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def insert_event(self, event: RouteEvent) -> int:
        now = time.time()
        with self._lock:
            connection = self._require()
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO events
                (source, bot_key, scene, chat_id, sender_id, sender_name,
                 message_id, occurred_at, text, user_consumed, group_consumed,
                 created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
                """,
                (
                    event.source,
                    event.bot_key,
                    event.scene,
                    event.chat_id,
                    event.sender_id,
                    event.sender_name,
                    event.message_id,
                    event.occurred_at,
                    event.text,
                    now,
                ),
            )
            if cursor.rowcount == 0 and event.message_id:
                row = connection.execute(
                    "SELECT id FROM events WHERE source = ? AND bot_key = ? AND message_id = ?",
                    (event.source, event.bot_key, event.message_id),
                ).fetchone()
                connection.commit()
                if row is not None:
                    return int(row["id"])
            connection.commit()
            self._prune(connection, now)
            return int(cursor.lastrowid)

    def candidates(
        self,
        event: RouteEvent,
        *,
        source: str,
        window: float,
        domain: str,
        chat_id: str | None = None,
    ) -> list[tuple[int, RouteEvent]]:
        consumed_column = "user_consumed" if domain == "user" else "group_consumed"
        with self._lock:
            connection = self._require()
            sql = f"""
                SELECT * FROM events
                WHERE source = ? AND {consumed_column} = 0 AND scene = ?
                  AND text = ? AND occurred_at BETWEEN ? AND ?
            """
            values: list[object] = [
                source,
                event.scene,
                event.text,
                event.occurred_at - window,
                event.occurred_at + window,
            ]
            if chat_id:
                sql += " AND chat_id = ?"
                values.append(chat_id)
            sql += " ORDER BY ABS(occurred_at - ?) ASC"
            values.append(event.occurred_at)
            rows = connection.execute(sql, values).fetchall()
            return [(int(row["id"]), self._row(row)) for row in rows]

    def mark_consumed(self, domain: str, *event_ids: int) -> None:
        if not event_ids:
            return
        column = "user_consumed" if domain == "user" else "group_consumed"
        with self._lock:
            connection = self._require()
            connection.executemany(
                f"UPDATE events SET {column} = 1 WHERE id = ?",
                [(int(event_id),) for event_id in event_ids],
            )
            connection.commit()

    def user_alias(self, *, official_bot_key: str, openid: str) -> dict | None:
        with self._lock:
            connection = self._require()
            row = connection.execute(
                "SELECT * FROM user_aliases WHERE official_bot_key = ? AND openid = ?",
                (official_bot_key, openid),
            ).fetchone()
            return dict(row) if row else None

    def group_alias(self, *, official_bot_key: str, group_openid: str) -> dict | None:
        with self._lock:
            connection = self._require()
            row = connection.execute(
                "SELECT * FROM group_aliases WHERE official_bot_key = ? AND group_openid = ?",
                (official_bot_key, group_openid),
            ).fetchone()
            return dict(row) if row else None

    def upsert_user_alias(
        self,
        *,
        official_bot_key: str,
        openid: str,
        qq_uin: str,
        scene: str,
        group_openid: str,
        confidence: int,
        status: str,
        evidence: dict,
    ) -> None:
        now = time.time()
        with self._lock:
            connection = self._require()
            connection.execute(
                """
                INSERT INTO users (qq_uin, first_seen, last_seen) VALUES (?, ?, ?)
                ON CONFLICT (qq_uin) DO UPDATE SET last_seen = excluded.last_seen
                """,
                (qq_uin, now, now),
            )
            connection.execute(
                """
                INSERT INTO user_aliases
                (official_bot_key, openid, qq_uin, scene, group_openid,
                 confidence, status, first_seen, last_seen, evidence_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (official_bot_key, openid) DO UPDATE SET
                    qq_uin = excluded.qq_uin,
                    scene = excluded.scene,
                    group_openid = excluded.group_openid,
                    confidence = MAX(user_aliases.confidence, excluded.confidence),
                    status = excluded.status,
                    last_seen = excluded.last_seen,
                    evidence_json = excluded.evidence_json
                """,
                (
                    official_bot_key,
                    openid,
                    qq_uin,
                    scene,
                    group_openid,
                    confidence,
                    status,
                    now,
                    now,
                    json.dumps(evidence, ensure_ascii=False, default=str),
                ),
            )
            connection.commit()

    def upsert_group_alias(
        self,
        *,
        official_bot_key: str,
        group_openid: str,
        qq_group_id: str,
        confidence: int,
        status: str,
        evidence: dict,
    ) -> None:
        now = time.time()
        with self._lock:
            connection = self._require()
            connection.execute(
                """
                INSERT INTO groups (qq_group_id, first_seen, last_seen) VALUES (?, ?, ?)
                ON CONFLICT (qq_group_id) DO UPDATE SET last_seen = excluded.last_seen
                """,
                (qq_group_id, now, now),
            )
            connection.execute(
                """
                INSERT INTO group_aliases
                (official_bot_key, group_openid, qq_group_id, confidence, status,
                 first_seen, last_seen, evidence_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (official_bot_key, group_openid) DO UPDATE SET
                    qq_group_id = excluded.qq_group_id,
                    confidence = MAX(group_aliases.confidence, excluded.confidence),
                    status = excluded.status,
                    last_seen = excluded.last_seen,
                    evidence_json = excluded.evidence_json
                """,
                (
                    official_bot_key,
                    group_openid,
                    qq_group_id,
                    confidence,
                    status,
                    now,
                    now,
                    json.dumps(evidence, ensure_ascii=False, default=str),
                ),
            )
            connection.commit()

    def resolve_user(self, *, official_bot_key: str, openid: str) -> dict | None:
        with self._lock:
            connection = self._require()
            row = connection.execute(
                """
                SELECT a.*, u.first_seen AS user_first_seen, u.last_seen AS user_last_seen
                FROM user_aliases a
                JOIN users u ON u.qq_uin = a.qq_uin
                WHERE a.official_bot_key = ? AND a.openid = ?
                """,
                (official_bot_key, openid),
            ).fetchone()
            return dict(row) if row else None

    def resolve_group(self, *, official_bot_key: str, group_openid: str) -> dict | None:
        with self._lock:
            connection = self._require()
            row = connection.execute(
                """
                SELECT a.*, g.first_seen AS group_first_seen, g.last_seen AS group_last_seen
                FROM group_aliases a
                JOIN groups g ON g.qq_group_id = a.qq_group_id
                WHERE a.official_bot_key = ? AND a.group_openid = ?
                """,
                (official_bot_key, group_openid),
            ).fetchone()
            return dict(row) if row else None

    def lookup_group_for_qq(self, qq_group_id: str) -> dict | None:
        with self._lock:
            connection = self._require()
            row = connection.execute(
                """
                SELECT * FROM group_aliases
                WHERE qq_group_id = ?
                ORDER BY last_seen DESC LIMIT 1
                """,
                (qq_group_id,),
            ).fetchone()
            return dict(row) if row else None

    def stats(self) -> dict:
        with self._lock:
            connection = self._require()
            return {
                "events": connection.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                "users": connection.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                "user_aliases": connection.execute(
                    "SELECT COUNT(*) FROM user_aliases"
                ).fetchone()[0],
                "groups": connection.execute("SELECT COUNT(*) FROM groups").fetchone()[0],
                "group_aliases": connection.execute(
                    "SELECT COUNT(*) FROM group_aliases"
                ).fetchone()[0],
            }

    def _prune(self, connection: sqlite3.Connection, now: float) -> None:
        connection.execute(
            "DELETE FROM events WHERE occurred_at < ?",
            (now - self.retention_seconds,),
        )
        connection.execute(
            "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)",
            (self.max_events,),
        )
        connection.commit()

    def _row(self, row: sqlite3.Row) -> RouteEvent:
        return RouteEvent(
            source=str(row["source"]),
            bot_key=str(row["bot_key"]),
            scene=str(row["scene"]),
            chat_id=str(row["chat_id"]),
            sender_id=str(row["sender_id"]),
            sender_name=str(row["sender_name"]),
            message_id=str(row["message_id"]),
            occurred_at=float(row["occurred_at"]),
            text=str(row["text"]),
            raw={},
        )

    def _require(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("辅助路由数据库尚未打开")
        return self._connection
