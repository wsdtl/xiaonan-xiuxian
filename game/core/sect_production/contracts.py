"""宗门资源生产的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


class SectProductionError(ValueError):
    """宗门资源生产无法完成当前请求。"""


@dataclass(frozen=True)
class SectProductionFacility:
    kind: Literal["灵脉", "灵田"]
    name: str
    period_seconds: int
    catch_up_limit: int
    base_multiplier: float
    primary_range: tuple[int, int]
    material_range: tuple[int, int]


@dataclass(frozen=True)
class SectProductionStatus:
    initialized: bool
    facilities: tuple[SectProductionFacility, ...]


@dataclass(frozen=True)
class SectProductionOutput:
    category: str
    content_id: str
    name: str
    grade_id: str
    grade_name: str
    quantity: int


@dataclass(frozen=True)
class SectProductionView:
    facility: SectProductionFacility
    role: str
    can_collect: bool
    started: bool
    last_settled_at: datetime | None
    pending_cycles: int
    next_cycle_seconds: int


@dataclass(frozen=True)
class SectProductionResult:
    view: SectProductionView
    newly_started: bool
    settled_cycles: int
    outputs: tuple[SectProductionOutput, ...]
    spirit_stones: int
    spirit_stones_after: int
    replayed: bool


__all__ = [
    "SectProductionError",
    "SectProductionFacility",
    "SectProductionOutput",
    "SectProductionResult",
    "SectProductionStatus",
    "SectProductionView",
]
