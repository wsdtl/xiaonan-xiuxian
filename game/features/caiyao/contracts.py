"""采药玩法微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from game.core.gathering import (
    GatheredItem,
    GatheringProgress,
    GatheringSettlement,
    GatheringStarted,
    GatheringUserSummary,
)


class HerbGatheringFeatureError(RuntimeError):
    """采药玩法无法完成请求。"""


@dataclass(frozen=True)
class HerbGatheringAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class HerbGatheringCopy:
    text: Mapping[str, Mapping[str, str]]


@dataclass(frozen=True)
class HerbGatheringEntry:
    """一次采药根命令的结果；分支合规由玩法判定。"""

    kind: str
    started: GatheringStarted | None = None
    progress: GatheringProgress | None = None
    settlement: GatheringSettlement | None = None
    page: int = 1
    total_pages: int = 1


__all__ = [
    "GatheredItem",
    "GatheringProgress",
    "GatheringSettlement",
    "GatheringStarted",
    "GatheringUserSummary",
    "HerbGatheringAction",
    "HerbGatheringCopy",
    "HerbGatheringEntry",
    "HerbGatheringFeatureError",
]
