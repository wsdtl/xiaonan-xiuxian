"""采集核心微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from game.core.innate_treasure import InnateTreasureActivation


class GatheringError(RuntimeError):
    """采集无法完成请求。"""


class GatheringStateError(GatheringError):
    """采集持久化状态不符合契约。"""


class GatheringConflictError(GatheringError):
    """参与者、位置或资产状态已经发生变化。"""


class GatheringLeaderRequiredError(GatheringError):
    """集体采集只能由领队统一结束。"""


@dataclass(frozen=True)
class GatheringModeStatus:
    kind: str
    resource_category: str
    state_id: str
    seconds_per_round: int
    maximum_rounds: int
    maximum_seconds: int
    draws_per_unit: int
    quantity_per_draw: int


@dataclass(frozen=True)
class GatheringStatus:
    initialized: bool
    modes: tuple[GatheringModeStatus, ...]


@dataclass(frozen=True)
class GatheringStartCommand:
    kind: str
    owner_user_id: str
    request_id: str
    participant_user_ids: tuple[str, ...]
    seed: int | None = None
    started_at: datetime | None = None


@dataclass(frozen=True)
class GatheringStarted:
    kind: str
    session_id: str
    place_name: str
    terrain: str
    participant_count: int
    gathering_unit_count: int
    maximum_rounds: int
    started_at: datetime
    maximum_ends_at: datetime
    replayed: bool
    #: 同行道侣数（正式名单里「并肩」的那部分）；人物数 = 正式单位数 − 道侣数。
    companion_count: int = 0


@dataclass(frozen=True)
class GatheredItem:
    item_id: str
    grade_id: str
    quantity: int


@dataclass(frozen=True)
class GatheringProgress:
    kind: str
    session_id: str
    place_name: str
    terrain: str
    participant_count: int
    completed_rounds: int
    maximum_rounds: int
    remaining_seconds: int
    maximum_reached: bool
    settled: bool
    can_end: bool
    group_quantity: int
    own_items: tuple[GatheredItem, ...]


@dataclass(frozen=True)
class GatheringUserSummary:
    user_id: str
    character_name: str
    assisting_companion_name: str
    items: tuple[GatheredItem, ...]
    treasure_activation: InnateTreasureActivation | None = None


@dataclass(frozen=True)
class GatheringSettlement:
    kind: str
    session_id: str
    place_name: str
    terrain: str
    completed_rounds: int
    maximum_rounds: int
    participant_count: int
    total_quantity: int
    users: tuple[GatheringUserSummary, ...]
    settled_at: datetime
    replayed: bool


__all__ = [
    "GatheredItem",
    "GatheringConflictError",
    "GatheringError",
    "GatheringLeaderRequiredError",
    "GatheringModeStatus",
    "GatheringProgress",
    "GatheringSettlement",
    "GatheringStartCommand",
    "GatheringStarted",
    "GatheringStateError",
    "GatheringStatus",
    "GatheringUserSummary",
]
