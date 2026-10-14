"""事务流水的落库与回读：表结构、SQL 原语与保留策略。

搬家说明：这些函数原来住在 `game/core/database/storage.py` 里（同名私有函数），2026-10-14 归位到这里，
成为独立核心微服务；`storage.py` 改为调用本模块，行为一字未改。
"""

from __future__ import annotations

import pathlib
import sqlite3
import time
from dataclasses import dataclass

RECEIPT_TTL_SECONDS = 7 * 24 * 3600
"""幂等回执的有效期：回执只需覆盖"重放一次"的窗口，不需要长期历史。"""


def log_db_path() -> pathlib.Path:
    """事务流水与消息流水、战报同库（路径的单一来源在 battle_report）。"""

    from game.core.database.battle_report import runtime_log_database_path

    return pathlib.Path(runtime_log_database_path())


def log_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(log_db_path())
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS log_committed_transactions (
            transaction_id TEXT PRIMARY KEY,
            user_id        TEXT NOT NULL,
            request_id     TEXT NOT NULL,
            business_type  TEXT NOT NULL,
            changes_json   TEXT NOT NULL,
            committed_at   TEXT NOT NULL,
            expires_at     REAL NOT NULL,
            scope          TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_log_committed_user_request "
        "ON log_committed_transactions(scope, user_id, request_id)"
    )
    return connection


def read_receipt_on(connection, scope: str, user_id: str, request_id: str):
    """收一个现成连接的回读：提交路径要在自己的事务里查，所以原语成对提供。"""

    return connection.execute(
        "SELECT transaction_id, business_type, changes_json, committed_at "
        "FROM log_committed_transactions "
        "WHERE scope = ? AND user_id = ? AND request_id = ? AND expires_at > ?",
        (scope, user_id, request_id, time.time()),
    ).fetchone()


def write_receipt_on(connection, scope, transaction_id, user_id, request_id, business_type, changes_json, committed_at) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO log_committed_transactions "
        "(transaction_id, user_id, request_id, business_type, changes_json, committed_at, expires_at, scope) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            transaction_id, user_id, request_id, business_type, changes_json,
            committed_at, time.time() + RECEIPT_TTL_SECONDS, scope,
        ),
    )


@dataclass(frozen=True)
class TransactionLogStatus:
    """事务流水微服务的启动状态。"""

    database: str
    table: str


class TransactionLogService:
    """事务流水微服务本体：组合根登记它；SQL 原语仍由本模块的函数提供。

    刻意做成薄壳——真正干活的是上面那几对原语，`storage.py` 的提交路径直接调用它们
    （它要在自己的两阶段事务里用 `*_on` 版本），不必持有本实例。
    """

    def __init__(self) -> None:
        self._status: TransactionLogStatus | None = None

    def initialize(self) -> TransactionLogStatus:
        if self._status is not None:
            raise RuntimeError("事务流水微服务已经初始化")
        connection = log_connection()
        try:
            connection.commit()
        finally:
            connection.close()
        self._status = TransactionLogStatus(
            str(log_db_path()), "log_committed_transactions"
        )
        return self._status

    def status(self) -> TransactionLogStatus:
        if self._status is None:
            raise RuntimeError("事务流水微服务尚未初始化")
        return self._status

    def read_receipt(self, scope: str, user_id: str, request_id: str):
        return read_receipt(scope, user_id, request_id)

    def write_receipt(
        self, scope, transaction_id, user_id, request_id, business_type, changes_json, committed_at
    ) -> None:
        write_receipt(
            scope, transaction_id, user_id, request_id, business_type, changes_json, committed_at
        )

    def count_receipts(self, scope: str) -> int:
        return count_receipts(scope)

    def prune_receipts(self, scope: str, keep_per_user: int) -> int:
        return prune_receipts(scope, keep_per_user)


def read_receipt(scope: str, user_id: str, request_id: str):
    connection = log_connection()
    try:
        return read_receipt_on(connection, scope, user_id, request_id)
    finally:
        connection.close()


def write_receipt(scope, transaction_id, user_id, request_id, business_type, changes_json, committed_at) -> None:
    connection = log_connection()
    try:
        write_receipt_on(
            connection, scope, transaction_id, user_id, request_id,
            business_type, changes_json, committed_at,
        )
        connection.commit()
    finally:
        connection.close()


def count_receipts(scope: str) -> int:
    connection = log_connection()
    try:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM log_committed_transactions WHERE scope = ?",
                (scope,),
            ).fetchone()[0]
        )
    finally:
        connection.close()


def prune_receipts(scope: str, keep_per_user: int) -> int:
    """每个玩家只保留最近 keep_per_user 条；返回删掉的条数。"""

    connection = log_connection()
    removed = 0
    try:
        owners = [
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT user_id FROM log_committed_transactions WHERE scope = ?",
                (scope,),
            ).fetchall()
        ]
        for owner in owners:
            found = int(
                connection.execute(
                    "SELECT COUNT(*) FROM log_committed_transactions WHERE scope = ? AND user_id = ?",
                    (scope, owner),
                ).fetchone()[0]
            )
            if found <= keep_per_user:
                continue
            connection.execute(
                "DELETE FROM log_committed_transactions WHERE scope = ? AND user_id = ? AND rowid NOT IN "
                "(SELECT rowid FROM log_committed_transactions WHERE scope = ? AND user_id = ? ORDER BY rowid DESC LIMIT ?)",
                (scope, owner, scope, owner, keep_per_user),
            )
            removed += found - keep_per_user
        connection.commit()
    finally:
        connection.close()
    return removed


__all__ = [
    "RECEIPT_TTL_SECONDS",
    "TransactionLogService",
    "TransactionLogStatus",
    "count_receipts",
    "log_connection",
    "log_db_path",
    "prune_receipts",
    "read_receipt",
    "read_receipt_on",
    "write_receipt",
    "write_receipt_on",
]