"""非资产日志库：核心侧的公共件。

非资产库（database/runtime_log.db）是核心的；这里放**与核心/框架边界有关的两件公共件**：
- BattleReportSink：产报方与仓储之间的协议（game/core/duel、game/core/sect_war 依赖它）；
- runtime_log_database_path：非资产库路径（核心的 storage 与维护者入口都要用）。

战报自己的读写实现在 game/features/zhanbao/battle_log/，它从这里 import（方向：features -> core）。
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol


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
    """非资产库（事务流水、消息流水、战报同住）的路径：**从游戏配置取**。

    2026-10-14 起非资产库与资产库对称，路径统一由 `game/config.py` 的 `GameRuntimeLogConfig`
    提供；在此之前这里自己读框架自定义项，等于核心反向依赖框架。
    """

    from game.config import game_config

    return game_config.runtime_log.path


