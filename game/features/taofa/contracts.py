"""讨伐玩法微服务的稳定公共契约。"""

from __future__ import annotations

from game.core.raid import (
    RaidProgress,
    RaidSettlement,
    RaidStarted,
)


class RaidFeatureError(RuntimeError):
    """讨伐命令无法完成。"""


__all__ = [
    "RaidFeatureError",
    "RaidProgress",
    "RaidSettlement",
    "RaidStarted",
]
