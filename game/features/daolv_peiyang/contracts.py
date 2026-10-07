"""道侣培养玩法的稳定请求与结果。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.companion import CompanionDefinition, CompanionInstance


class CompanionCultivationFeatureError(ValueError):
    """当前同行道侣不能完成培养请求。"""


class CompanionCultivationConflictError(RuntimeError):
    """道侣培养期间同行事实或实例已经变化。"""


@dataclass(frozen=True)
class CompanionCultivationView:
    definition: CompanionDefinition
    instance: CompanionInstance
    realm_name: str
    weapon_stage: str
    open_law_slots: int
    cultivation_names: tuple[tuple[str, tuple[str, ...]], ...]
    weapon_law_names: tuple[tuple[int, str], ...]
    next_experience: int
    weapon_next_experience: int


@dataclass(frozen=True)
class CompanionBreakthroughRequest:
    user_id: str
    request_id: str
    medicine: str


@dataclass(frozen=True)
class CompanionLawRequest:
    user_id: str
    request_id: str
    law: str
    slot: int


@dataclass(frozen=True)
class CompanionBreakthroughResult:
    view: CompanionCultivationView
    medicine_name: str
    #: 消耗的那份丹药的品级。品级是实例级事实，消耗的是具体哪一品必须露出来。
    medicine_grade: str
    replayed: bool


@dataclass(frozen=True)
class CompanionLawResult:
    view: CompanionCultivationView
    law_name: str
    slot: int
    replayed: bool


__all__ = [
    "CompanionBreakthroughRequest",
    "CompanionBreakthroughResult",
    "CompanionCultivationConflictError",
    "CompanionCultivationFeatureError",
    "CompanionCultivationView",
    "CompanionLawRequest",
    "CompanionLawResult",
]
