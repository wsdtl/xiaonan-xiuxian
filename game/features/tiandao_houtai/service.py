"""消息流水仓储的兼容导出：实现已归 `game/core/database`。

天道后台是维护者入口，只读这份观测流水；仓储本身是非资产日志基础设施。
"""

from __future__ import annotations

from game.core.database.message_flow_store import (
    MESSAGE_RETENTION_SECONDS,
    MessageFlowRow,
    MessageFlowStore,
)

__all__ = [
    "MESSAGE_RETENTION_SECONDS",
    "MessageFlowRow",
    "MessageFlowStore",
]
