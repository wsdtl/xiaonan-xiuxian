"""炼器与本命武器规则的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from game.core.innate_treasure import InnateTreasureActivation
from game.core.world import CraftFacility


class ForgingError(ValueError):
    """炼器规则或请求无法完成。"""


class ForgingUnavailableError(ForgingError):
    """当前位置不能炼器。"""


class ForgingMaterialError(ForgingError):
    """纳戒材料或灵石不足以完成炼制。"""


class ForgingConflictError(ForgingError):
    """炼器提交时相关状态已经变化。"""


@dataclass(frozen=True)
class ForgingStatus:
    initialized: bool
    law_count: int
    facility_count: int
    beast_treasure_count: int
    mineral_count: int
    weapon_maximum_level: int


@dataclass(frozen=True)
class WeaponStage:
    name: str
    minimum_level: int
    maximum_level: int
    open_law_slots: int
    mineral_requirement_range: tuple[int, int]
    minimum_mineral_grade_id: str


@dataclass(frozen=True)
class WeaponAdvance:
    level_before: int
    level_after: int
    experience_before: int
    experience_after: int
    experience_gained: int
    stage_before: str
    stage_after: str
    open_slots_before: int
    open_slots_after: int


@dataclass(frozen=True)
class ForgingLaw:
    law_id: str
    name: str
    stage: str
    materials: tuple[Mapping[str, object], ...] = ()


@dataclass(frozen=True)
class ForgingMaterial:
    item_id: str
    name: str
    grade_id: str
    grade_name: str
    trait: str
    relation: str
    quantity: int


@dataclass(frozen=True)
class ForgingMissingMaterial:
    category: str
    trait: str
    quantity: int


@dataclass(frozen=True)
class ForgingAssessment:
    law: ForgingLaw
    beast_materials: tuple[ForgingMaterial, ...]
    mineral_materials: tuple[ForgingMaterial, ...]
    missing_materials: tuple[ForgingMissingMaterial, ...]
    can_forge: bool


@dataclass(frozen=True)
class ForgingPreview:
    user_id: str
    location_name: str
    facility: CraftFacility | None
    law: ForgingLaw
    beast_materials: tuple[ForgingMaterial, ...]
    mineral_materials: tuple[ForgingMaterial, ...]
    missing_materials: tuple[ForgingMissingMaterial, ...]
    can_forge: bool
    quantity: int = 1
    spirit_stone_cost: int = 0


@dataclass(frozen=True)
class ForgingLawEntry:
    law: ForgingLaw
    can_forge: bool
    missing_count: int


@dataclass(frozen=True)
class ForgingOverview:
    user_id: str
    location_name: str
    facility: CraftFacility | None
    stage_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class ForgingLawList:
    user_id: str
    location_name: str
    facility: CraftFacility | None
    stage: str
    entries: tuple[ForgingLawEntry, ...]


@dataclass(frozen=True)
class ForgingResult:
    preview: ForgingPreview
    quantity_before: int
    quantity_after: int
    replayed: bool
    treasure_activation: InnateTreasureActivation | None = None


__all__ = [
    "ForgingAssessment",
    "ForgingConflictError",
    "ForgingError",
    "ForgingLaw",
    "ForgingLawEntry",
    "ForgingLawList",
    "ForgingMaterial",
    "ForgingMaterialError",
    "ForgingMissingMaterial",
    "ForgingOverview",
    "ForgingPreview",
    "ForgingResult",
    "ForgingStatus",
    "ForgingUnavailableError",
    "WeaponAdvance",
    "WeaponStage",
]
