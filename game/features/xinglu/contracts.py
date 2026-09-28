"""即时行路玩法的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.world import JourneyPlan
from game.core.world import LocationView


class TravelError(RuntimeError):
    """即时行路无法完成。"""


class TravelQueryError(TravelError, ValueError):
    """玩家提交的目的地无效。"""


class TravelConflictError(TravelError):
    """人物位置在行路结算前已经改变。"""


@dataclass(frozen=True)
class TravelRequest:
    user_id: str
    request_id: str
    destination: str


@dataclass(frozen=True)
class TravelResult:
    plan: JourneyPlan
    participant_user_ids: tuple[str, ...]
    replayed: bool


__all__ = [
    "TravelConflictError",
    "TravelError",
    "TravelQueryError",
    "TravelRequest",
    "TravelResult",
    "LocationView",
]
