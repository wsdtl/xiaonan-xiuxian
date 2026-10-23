"""炼器与本命武器规则的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from game.core.innate_treasure import InnateTreasureActivation


class ForgingError(ValueError):
    """炼器规则或请求无法完成。"""


class ForgingUnavailableError(ForgingError):
    """当前位置不能炼器。"""


class ForgingMaterialError(ForgingError):
    """纳戒材料不足以完成炼制。"""


class ForgingConflictError(ForgingError):
    """炼器提交时相关状态已经变化。"""


@dataclass(frozen=True)
class ForgingStatus:
    initialized: bool
    law_count: int
    method_count: int
    artisan_count: int
    beast_treasure_count: int
    mineral_count: int
    weapon_maximum_level: int


@dataclass(frozen=True)
class WeaponStage:
    name: str
    minimum_level: int
    maximum_level: int
    open_law_slots: int
    beast_requirement_count: int
    mineral_requirement_range: tuple[int, int]
    secondary_substitution_limit: int
    minimum_beast_grade_id: str
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
class ForgingArtisan:
    artisan_id: str
    name: str
    location_name: str
    title: str
    furnace_name: str
    speech_style: str
    speech: Mapping[str, str]


@dataclass(frozen=True)
class ForgingLaw:
    law_id: str
    name: str
    stage: str
    method: str
    beast_traits: tuple[str, ...]
    mineral_traits: tuple[str, ...]


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
    secondary_substitutions: int
    secondary_substitution_limit: int
    can_forge: bool


@dataclass(frozen=True)
class ForgingPreview:
    user_id: str
    location_name: str
    artisan: ForgingArtisan
    law: ForgingLaw
    beast_materials: tuple[ForgingMaterial, ...]
    mineral_materials: tuple[ForgingMaterial, ...]
    missing_materials: tuple[ForgingMissingMaterial, ...]
    secondary_substitutions: int
    secondary_substitution_limit: int
    can_forge: bool


@dataclass(frozen=True)
class ForgingLawEntry:
    law: ForgingLaw
    can_forge: bool
    missing_count: int


@dataclass(frozen=True)
class ForgingOverview:
    user_id: str
    location_name: str
    artisan: ForgingArtisan
    stage_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class ForgingLawList:
    user_id: str
    location_name: str
    artisan: ForgingArtisan
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
    "ForgingArtisan",
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
