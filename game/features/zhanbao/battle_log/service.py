"""运行期非资产记录：短期战报仓储。

战报是**非资产数据**：不归任何玩家拥有，只按编号对外分享，只留一段时间；
因此与事务流水、消息流水同住在非资产库（database/runtime_log.db），共用 expires_at 与定时清理。

**为什么在 launch/（框架层）**：维护者入口「天道后台」（game/cmd/后台/天道后台）要读它，
而架构判据规定**维护者入口不得导入 game.***（启动报「后台越界读取游戏」），
而且命令层也不得直接 import 核心；所以这份仓储与「非资产日志库在哪」必须待在框架层，
供 game/ 侧与后台侧同时使用。

（2026-10-14 核对：旧注释曾写「命令组件包名是中文、装配点只能按 ASCII 导入」——那不是真原因，
真正的原因是上面这条「后台只能读框架」的判据。）"""

from __future__ import annotations

from game.core.database.battle_report import (
    BattleReportSink,
    runtime_log_database_path,
)

import base64
import sqlite3
import time
import zlib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

#: 战报本体的打包前缀：存进去前 zlib 最高级别压缩，读出来再解。战报比消息重得多，不压会撑爆库。
_PACK_PREFIX = "gz:"


def _pack(text: str) -> str:
    """战报本体按**最高压缩级别**（zlib 9 级）打包；已经是打包形态的原样返回。"""

    if not text or text.startswith(_PACK_PREFIX):
        return text
    return _PACK_PREFIX + base64.b64encode(
        zlib.compress(text.encode("utf-8"), 9)
    ).decode("ascii")


def _unpack(text: str) -> str:
    """读回战报本体；没有前缀的（历史明文行）原样返回。"""

    if not text.startswith(_PACK_PREFIX):
        return text
    return zlib.decompress(base64.b64decode(text[len(_PACK_PREFIX) :])).decode("utf-8")


#: 战报比消息重得多：同样按到期清理，但留得久（7 天），条数上限也更宽。
BATTLE_MAX_ROWS = 2_000
BATTLE_RETENTION_SECONDS = 7 * 24 * 60 * 60

#: 战报类型：只有这几种会被登记，别的取值一律拒绝。
KINDS = ("切磋", "宗门战", "探险")


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
                    _pack(str(report_json)),
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
        report_json=_unpack(str(row["report_json"])),
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