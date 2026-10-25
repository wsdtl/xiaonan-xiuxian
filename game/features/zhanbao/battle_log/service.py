"""战报仓储的兼容导出：实现已归 `game/core/database`。

战报是非资产日志，核心切磋/宗门战需要同一个 sink；玩法 `zhanbao` 只读。
"""

from __future__ import annotations

from game.core.database.battle_report import BattleReportSink
from game.core.database.battle_report_store import (
    BATTLE_MAX_ROWS,
    BATTLE_RETENTION_SECONDS,
    BattleReportRow,
    BattleReportStore,
    KINDS,
    runtime_log_database_path,
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
