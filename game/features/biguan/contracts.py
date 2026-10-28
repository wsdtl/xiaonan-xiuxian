"""闭关玩法微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from game.core.retreat import (
    RetreatProgress,
    RetreatSettlement,
    RetreatStarted,
    RetreatUserSummary,
)


class RetreatFeatureError(RuntimeError):
    """闭关玩法无法完成请求。"""


@dataclass(frozen=True)
class RetreatAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class RetreatCopy:
    text: Mapping[str, Mapping[str, str]]


@dataclass(frozen=True)
class RetreatEntry:
    """一次根命令进入后的结果；分支合规由玩法判定。"""

    kind: str
    started: RetreatStarted | None = None
    progress: RetreatProgress | None = None
    settlement: RetreatSettlement | None = None


__all__ = [
    "RetreatAction",
    "RetreatCopy",
    "RetreatEntry",
    "RetreatFeatureError",
    "RetreatProgress",
    "RetreatSettlement",
    "RetreatStarted",
    "RetreatUserSummary",
]
