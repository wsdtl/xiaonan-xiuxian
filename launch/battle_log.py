"""运行期非资产记录：短期战报仓储。

战报是**非资产数据**：它不归任何玩家拥有，只按战报编号对外分享，并且只留一段时间。
因此它不进资产库（`game.db` 的玩家状态），而与消息流水同住在非资产库
（`database/runtime_log.db`），用同一套 `expires_at` + 定时清理来过期。

放在 `launch/` 而不是命令组件里：命令组件的包名是中文，而 `game/app.py` 这类装配点必须用
ASCII 标识符导入它（架构边界判据：标识符不许是中文）。
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Protocol

#: 战报比消息重得多：同样按到期清理，但留得久（7 天），条数上限也更宽。
BATTLE_MAX_ROWS = 2_000
BATTLE_RETENTION_SECONDS = 7 * 24 * 60 * 60

#: 战报类型：只有这几种会被登记，别的取值一律拒绝。
KINDS = ("切磋", "宗门战", "探险")


class BattleReportSink(Protocol):
    """战报的去处契约：核心服务只认它，不直接开非资产库。

    由 `BattleReportStore` 实现；两个产出战报的核心（切磋、宗门战）都通过它登记。
    """

    def save(
        self,
        *,
        report_id: str,
        kind: str,
        participants: Sequence[str],
        finished_at: str,
        finished_timestamp: float,
        report_json: str,
    ) -> object: ...

    def load(self, report_id: str) -> object | None: ...


def runtime_log_database_path() -> Path:
    """非资产库（消息流水与战报同住）的路径。

    维护者入口自己解释框架自定义项，不经过 `game/config.py`：游戏配置只登记游戏自身拥有的
    事实库，运行期观察库不进入游戏配置面。相对路径按项目根解析。
    """

    from launch import config

    raw = (config.custom.get("RUNTIME_LOG_DATABASE_PATH", "") or "").strip()
    path = Path(raw or "database/runtime_log.db").expanduser()
    return path if path.is_absolute() else config.base_dir / path


@dataclass(frozen=True)
class BattleReportRow:
    """持久化层返回的原始战报行。"""

    report_id: str
    kind: str
    participants: str
    finished_at: str
    finished_timestamp: float
    report_json: str
    expires_at: float


class BattleReportStore:
    """只负责非资产战报表的写入、按编号读取与过期清理，不解释战报内容。"""

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
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS log_battle_reports (
                    report_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    participants TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    finished_timestamp REAL NOT NULL,
                    report_json TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_log_battle_reports_expires
                ON log_battle_reports(expires_at);
                CREATE INDEX IF NOT EXISTS ix_log_battle_reports_finished
                ON log_battle_reports(finished_timestamp);
                """
            )

    def save(
        self,
        *,
        report_id: str,
        kind: str,
        participants: Sequence[str],
        finished_at: str,
        finished_timestamp: float,
        report_json: str,
    ) -> BattleReportRow:
        """按编号登记一份战报；同一编号重复登记以最后一次为准。"""

        identifier = str(report_id or "").strip()
        if not identifier:
            raise ValueError("战报编号必须是非空文本")
        if kind not in KINDS:
            raise ValueError(f"战报类型只能是：{'、'.join(KINDS)}")
        if not str(report_json or "").strip():
            raise ValueError("战报本体不能为空")
        names = tuple(str(name) for name in participants)
        expires_at = float(finished_timestamp) + self.retention_seconds
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO log_battle_reports (
                    report_id, kind, participants, finished_at,
                    finished_timestamp, report_json, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(report_id) DO UPDATE SET
                    kind = excluded.kind,
                    participants = excluded.participants,
                    finished_at = excluded.finished_at,
                    finished_timestamp = excluded.finished_timestamp,
                    report_json = excluded.report_json,
                    expires_at = excluded.expires_at
                """,
                (
                    identifier,
                    kind,
                    "\n".join(names),
                    str(finished_at),
                    float(finished_timestamp),
                    str(report_json),
                    expires_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM log_battle_reports WHERE report_id = ?",
                (identifier,),
            ).fetchone()
        if row is None:
            raise RuntimeError("战报写入后无法读取")
        return _row(row)

    def load(self, report_id: str) -> BattleReportRow | None:
        """按编号取一份**尚未过期**的战报；过期或不存在的都回 None。"""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM log_battle_reports WHERE report_id = ? AND expires_at > ?",
                (str(report_id or "").strip(), time.time()),
            ).fetchone()
        return _row(row) if row is not None else None

    def peek(self, report_id: str) -> BattleReportRow | None:
        """按编号取一份战报，**不看是否过期**。

        页面要能把「已经过期」与「从来没有过」分开说话：前者说记录已过期，后者说不存在。
        """

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM log_battle_reports WHERE report_id = ?",
                (str(report_id or "").strip(),),
            ).fetchone()
        return _row(row) if row is not None else None

    def cleanup(self, *, now_timestamp: float, max_rows: int) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM log_battle_reports WHERE expires_at <= ?",
                (float(now_timestamp),),
            )
            connection.execute(
                """
                DELETE FROM log_battle_reports
                WHERE report_id NOT IN (
                    SELECT report_id FROM log_battle_reports
                    ORDER BY finished_timestamp DESC LIMIT ?
                )
                """,
                (max(1, int(max_rows)),),
            )
            connection.execute("PRAGMA optimize")
            if int(connection.execute("PRAGMA auto_vacuum").fetchone()[0]) == 2:
                connection.execute("PRAGMA incremental_vacuum(128)")

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


def _row(row: sqlite3.Row | tuple[object, ...]) -> BattleReportRow:
    return BattleReportRow(
        report_id=str(row["report_id"]),
        kind=str(row["kind"]),
        participants=str(row["participants"]),
        finished_at=str(row["finished_at"]),
        finished_timestamp=float(row["finished_timestamp"]),
        report_json=str(row["report_json"]),
        expires_at=float(row["expires_at"]),
    )


__all__ = [
    "BATTLE_MAX_ROWS",
    "BATTLE_RETENTION_SECONDS",
    "BattleReportRow",
    "BattleReportSink",
    "BattleReportStore",
    "KINDS",
    "runtime_log_database_path",
]
