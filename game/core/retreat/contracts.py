"""闭关核心微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from game.core.innate_treasure import InnateTreasureActivation


class RetreatError(RuntimeError):
    """闭关无法完成请求。"""


class RetreatStateError(RetreatError):
    """闭关持久化状态不符合契约。"""


class RetreatConflictError(RetreatError):
    """参与者、位置或资产状态已经发生变化。"""


class RetreatLeaderRequiredError(RetreatError):
    """集体闭关只能由领队带领出关。"""


@dataclass(frozen=True)
class RetreatStatus:
    initialized: bool
    seconds_per_round: int
    maximum_rounds: int
    maximum_seconds: int
    insight_probability: float


@dataclass(frozen=True)
class RetreatStartCommand:
    owner_user_id: str
    request_id: str
    participant_user_ids: tuple[str, ...]
    seed: int | None = None
    started_at: datetime | None = None


@dataclass(frozen=True)
class RetreatStarted:
    session_id: str
    location_name: str
    participant_count: int
    formal_character_count: int
    maximum_rounds: int
    started_at: datetime
    maximum_ends_at: datetime
    replayed: bool
    #: 同行道侣数（正式名单里「并肩」的那部分）；人物数 = 正式单位数 − 道侣数。
    companion_count: int = 0


@dataclass(frozen=True)
class RetreatInsight:
    round_number: int
    content_id: str
    grade_id: str
    outcome: str | None = None


@dataclass(frozen=True)
class RetreatProgress:
    session_id: str
    location_name: str
    participant_count: int
    completed_rounds: int
    maximum_rounds: int
    remaining_seconds: int
    maximum_reached: bool
    settled: bool
    can_end: bool
    group_insight_count: int
    own_insights: tuple[RetreatInsight, ...]


@dataclass(frozen=True)
class RetreatCharacterSummary:
    name: str
    companion: bool
    experience_gained: int
    level_before: int
    level_after: int
    health: float
    spirit: float
    injury_changes: tuple[tuple[str, int, int], ...] = ()
    injuries: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class RetreatUserSummary:
    user_id: str
    character_name: str
    characters: tuple[RetreatCharacterSummary, ...]
    insights: tuple[RetreatInsight, ...]
    treasure_activation: InnateTreasureActivation | None = None


@dataclass(frozen=True)
class RetreatSettlement:
    session_id: str
    location_name: str
    completed_rounds: int
    maximum_rounds: int
    participant_count: int
    users: tuple[RetreatUserSummary, ...]
    settled_at: datetime
    replayed: bool


__all__ = [
    "RetreatCharacterSummary",
    "RetreatConflictError",
    "RetreatError",
    "RetreatInsight",
    "RetreatLeaderRequiredError",
    "RetreatProgress",
    "RetreatSettlement",
    "RetreatStartCommand",
    "RetreatStarted",
    "RetreatStateError",
    "RetreatStatus",
    "RetreatUserSummary",
]
