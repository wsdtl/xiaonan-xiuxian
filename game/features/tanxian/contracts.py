"""普通探险玩法微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from game.core.exploration import (
    ExplorationProgress,
    ExplorationSettlement,
    ExplorationStarted,
    ExplorationUserSummary,
)


class ExplorationFeatureError(RuntimeError):
    """普通探险玩法无法完成请求。"""


@dataclass(frozen=True)
class ExplorationAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class ExplorationCopy:
    text: Mapping[str, Mapping[str, str]]


@dataclass(frozen=True)
class ExplorationEntry:
    """一次根命令进入后的结果；分支合规由玩法判定。"""

    kind: str
    started: ExplorationStarted | None = None
    progress: ExplorationProgress | None = None
    settlement: ExplorationSettlement | None = None


__all__ = [
    "ExplorationAction",
    "ExplorationCopy",
    "ExplorationEntry",
    "ExplorationFeatureError",
    "ExplorationProgress",
    "ExplorationSettlement",
    "ExplorationStarted",
    "ExplorationUserSummary",
]
