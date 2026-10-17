"""求子请求的短期存储：住在非资产日志库（runtime_log.db）。

请求是**非资产数据**：它不属于任何玩家、只活很短一段时间（默认 600 秒），
过期即失效；因此与事务流水、消息流水、战报同住一个日志库，不写玩家存档，
也不占角色服务的写入权。日志被清理了就当作请求不存在。

边界：本模块只做表结构、SQL 与过期清理，不解释生育规则、不校验性别与地点。
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

PENDING = "pending"
DONE = "done"
REFUSED = "refused"

STATUSES = frozenset({PENDING, DONE, REFUSED})


@dataclass(frozen=True)
class BirthRequestRow:
    """日志库里的一行求子请求。"""

    request_id: str
    asker_id: str
    asker_name: str
    target_id: str
    target_name: str
    created_at: str
    created_at_timestamp: float
    expires_at: float
    status: str
    result_code: str


class BirthRequestStore:
    """只负责请求表的写入、读取、标记与过期清理。"""

    def __init__(self, path: Path | str, *, busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path)
        self.busy_timeout_ms = max(1, int(busy_timeout_ms))
        self._lock = RLock()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS log_birth_requests (
                    request_id TEXT PRIMARY KEY,
                    asker_id TEXT NOT NULL,
                    asker_name TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_at_timestamp REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result_code TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS ix_log_birth_requests_target
                ON log_birth_requests(target_id, status);
                CREATE INDEX IF NOT EXISTS ix_log_birth_requests_asker
                ON log_birth_requests(asker_id, status);
                CREATE INDEX IF NOT EXISTS ix_log_birth_requests_expires
                ON log_birth_requests(expires_at);
                """
            )

    def create(
        self,
        *,
        request_id: str,
        asker_id: str,
        asker_name: str,
        target_id: str,
        target_name: str,
        seconds: int,
        now: float | None = None,
    ) -> BirthRequestRow:
        """登记一条待回应的请求；编号重复直接拒绝（不覆盖旧请求）。"""

        identifier = str(request_id or "").strip()
        if not identifier:
            raise ValueError("求子请求编号必须是非空文本")
        stamp = float(time.time() if now is None else now)
        created_at = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(stamp))
        expires_at = stamp + max(1, int(seconds))
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO log_birth_requests ("
                "request_id, asker_id, asker_name, target_id, target_name,"
                "created_at, created_at_timestamp, expires_at, status, result_code"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    str(asker_id),
                    str(asker_name),
                    str(target_id),
                    str(target_name),
                    created_at,
                    stamp,
                    expires_at,
                    PENDING,
                    "",
                ),
            )
            row = self._row(connection, identifier)
        if row is None:
            raise RuntimeError("求子请求写入后无法读取")
        self.cleanup(now=stamp)
        return row

    def find(self, request_id: str) -> BirthRequestRow | None:
        """按编号取一条请求，**不看是否过期**（过期由调用方判断并解释）。"""

        identifier = str(request_id or "").strip()
        if not identifier:
            return None
        with self._lock, self._connect() as connection:
            return self._row(connection, identifier)

    def open_for(self, target_id: str, *, now: float | None = None) -> list[BirthRequestRow]:
        """发给某人的、仍待回应且未过期的请求，最新的在前。"""

        stamp = float(time.time() if now is None else now)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM log_birth_requests "
                "WHERE target_id = ? AND status = ? AND expires_at > ? "
                "ORDER BY created_at_timestamp DESC",
                (str(target_id), PENDING, stamp),
            ).fetchall()
        return [_convert(row) for row in rows]

    def latest_open_for(self, target_id: str, *, now: float | None = None) -> BirthRequestRow | None:
        rows = self.open_for(target_id, now=now)
        return rows[0] if rows else None

    def open_from(self, asker_id: str, *, now: float | None = None) -> BirthRequestRow | None:
        """某个求方还有没有未过期的待回应请求（同一时间只许挂一条）。"""

        stamp = float(time.time() if now is None else now)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM log_birth_requests "
                "WHERE asker_id = ? AND status = ? AND expires_at > ? "
                "ORDER BY created_at_timestamp DESC LIMIT 1",
                (str(asker_id), PENDING, stamp),
            ).fetchone()
        return _convert(row) if row is not None else None

    def mark(self, request_id: str, status: str, *, result_code: str = "") -> None:
        """标记已处理；只允许 pending -> done/refused 这一条路。"""

        desired = str(status or "").strip()
        if desired not in {DONE, REFUSED}:
            raise ValueError("求子请求只能标记为 done 或 refused")
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE log_birth_requests SET status = ?, result_code = ? "
                "WHERE request_id = ? AND status = ?",
                (desired, str(result_code or ""), str(request_id), PENDING),
            )
            return int(cursor.rowcount or 0) > 0

    def cleanup(self, *, now: float | None = None) -> int:
        """删掉过期请求；日志滚掉了就等于没有这条请求。"""

        stamp = float(time.time() if now is None else now)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM log_birth_requests WHERE expires_at <= ?", (stamp,)
            )
            return int(cursor.rowcount or 0)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA busy_timeout = %d" % self.busy_timeout_ms)
        connection.row_factory = sqlite3.Row
        return _Closing(connection)

    def _row(self, connection: sqlite3.Connection, request_id: str) -> BirthRequestRow | None:
        row = connection.execute(
            "SELECT * FROM log_birth_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        return _convert(row) if row is not None else None


class _Closing:
    """让 `with self._connect() as connection` 在退出时**提交并关闭**（sqlite3 的上下文只管提交）。"""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def __enter__(self) -> sqlite3.Connection:
        return self._connection

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            if exc_type is None:
                self._connection.commit()
        finally:
            self._connection.close()

    def __getattr__(self, name: str) -> object:
        return getattr(self._connection, name)


def _convert(row) -> BirthRequestRow:
    return BirthRequestRow(
        request_id=str(row["request_id"]),
        asker_id=str(row["asker_id"]),
        asker_name=str(row["asker_name"]),
        target_id=str(row["target_id"]),
        target_name=str(row["target_name"]),
        created_at=str(row["created_at"]),
        created_at_timestamp=float(row["created_at_timestamp"]),
        expires_at=float(row["expires_at"]),
        status=str(row["status"]),
        result_code=str(row["result_code"]),
    )


__all__ = [
    "DONE",
    "PENDING",
    "REFUSED",
    "STATUSES",
    "BirthRequestRow",
    "BirthRequestStore",
]
