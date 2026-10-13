"""非资产日志：战报仓储（战报微服务侧）。

非资产库（database/runtime_log.db）里 log_battle_reports 这一张表——
按战报编号整条读写，到期清理。二级命令组件「专属/战报」与维护者入口都经本包读它。
"""
from .service import (
    BATTLE_MAX_ROWS,
    BATTLE_RETENTION_SECONDS,
    BattleReportRow,
    BattleReportSink,
    BattleReportStore,
    runtime_log_database_path,
)

__all__ = [
    "BATTLE_MAX_ROWS",
    "BATTLE_RETENTION_SECONDS",
    "BattleReportRow",
    "BattleReportSink",
    "BattleReportStore",
    "runtime_log_database_path",
]
