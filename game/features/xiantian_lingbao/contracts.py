"""先天灵宝玩法的稳定请求与结果。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.innate_treasure import InnateTreasure


class InnateTreasureFeatureError(ValueError):
    """先天灵宝查看或执掌请求不合法。"""


class InnateTreasureFeatureConflictError(RuntimeError):
    """提交时灵宝谱已经变化。"""


@dataclass(frozen=True)
class InnateTreasureView:
    active: InnateTreasure | None
    owned: tuple[InnateTreasure, ...]
    page: int
    page_count: int
    total_count: int


@dataclass(frozen=True)
class InnateTreasureEquipRequest:
    user_id: str
    request_id: str
    treasure: str


@dataclass(frozen=True)
class InnateTreasureEquipResult:
    treasure: InnateTreasure
    replayed: bool


__all__ = [
    "InnateTreasureEquipRequest",
    "InnateTreasureEquipResult",
    "InnateTreasureFeatureConflictError",
    "InnateTreasureFeatureError",
    "InnateTreasureView",
    "InnateTreasure",
]
