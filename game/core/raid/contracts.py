"""讨伐业务的稳定契约。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from game.core.enemy import EnemyGroup


@dataclass(frozen=True)
class RaidDefinition:
    raid_id: str
    boss_pool: tuple[str, ...]
    support_pool: tuple[str, ...]
    subordinate_pool: tuple[str, ...]
    boss_tier: str
    support_tier: str
    subordinate_tier: str
    reward_pool: tuple[str, ...] = ()
    boss_unit_count: tuple[int, int] = (1, 1)
    support_unit_count: tuple[int, int] = (0, 1)
    subordinate_unit_count: tuple[int, int] = (2, 3)


@dataclass(frozen=True)
class RaidGroupResult:
    """讨伐生成阶段的敌方结果包装，提交战斗时转换为公共编组契约。"""

    boss_group: EnemyGroup
    subordinate_groups: tuple[EnemyGroup, ...]

    @property
    def groups(self) -> tuple[EnemyGroup, ...]:
        return (self.boss_group, *self.subordinate_groups)


class RaidError(RuntimeError):
    """讨伐业务无法完成请求。"""


class RaidNotFinishedError(RaidError):
    """讨伐尚未到结算时间。"""


class RaidLeaderRequiredError(RaidError):
    """讨伐只能由发起者结算。"""


@dataclass(frozen=True)
class RaidStartCommand:
    owner_user_id: str
    request_id: str
    participant_user_ids: tuple[str, ...]
    seed: int | None = None
    started_at: datetime | None = None


@dataclass(frozen=True)
class RaidStarted:
    session_id: str
    location_name: str
    participant_count: int
    enemy_group_count: int
    started_at: datetime
    ends_at: datetime
    replayed: bool


@dataclass(frozen=True)
class RaidProgress:
    session_id: str
    location_name: str
    remaining_seconds: int
    ended: bool
    boss_phase: int
    boss_phases: int
    can_settle: bool


@dataclass(frozen=True)
class RaidSettlement:
    session_id: str
    location_name: str
    winner: str
    participant_count: int
    defeated_enemies: int
    settled_at: datetime
    replayed: bool


__all__ = [
    "RaidDefinition",
    "RaidError",
    "RaidGroupResult",
    "RaidLeaderRequiredError",
    "RaidNotFinishedError",
    "RaidProgress",
    "RaidSettlement",
    "RaidStartCommand",
    "RaidStarted",
]
