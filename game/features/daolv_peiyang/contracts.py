"""道侣培养玩法的稳定请求与结果。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.companion import (
    CompanionBreakthroughPreview,
    CompanionDefinition,
    CompanionInstance,
)


class CompanionCultivationFeatureError(ValueError):
    """当前同行道侣不能完成培养请求。"""


class CompanionCultivationConflictError(RuntimeError):
    """道侣培养期间同行事实或实例已经变化。"""


@dataclass(frozen=True)
class CompanionBreakthroughCandidate:
    """一颗候选突破丹：编号是句柄、名称只作显示，永久属性照数据原样带出。"""

    medicine_id: str
    name: str
    permanent: tuple[tuple[str, int | float], ...] = ()


@dataclass(frozen=True)
class CompanionBreakthroughOffer:
    """「道侣能不能突破、下一境界是什么、有哪些丹可用」——与人物培养同一套形状。"""

    preview: CompanionBreakthroughPreview
    candidates: tuple[CompanionBreakthroughCandidate, ...] = ()


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
    #: 突破预览与候选丹药；没有下一境界时也在，用 `preview.reason` 说话。
    breakthrough: CompanionBreakthroughOffer | None = None


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




@dataclass(frozen=True)
class DaolvPeiyangAction:
    """道侣培养回执上的动作，字段名与 CommandAction 契约一致。"""

    action_id: str
    label: str
    command: str
    behavior: str
    style: str


__all__ = [
    "CompanionBreakthroughCandidate",
    "CompanionBreakthroughOffer",
    "CompanionBreakthroughRequest",
    "CompanionBreakthroughResult",
    "CompanionCultivationConflictError",
    "CompanionCultivationFeatureError",
    "CompanionCultivationView",
    "CompanionLawRequest",
    "CompanionLawResult",
]
