"""宗门洞天设施的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from game.core.alchemy import AlchemyAssessment
from game.core.forging import ForgingAssessment
from game.core.formation import FormationAssessment


class SectFacilityError(ValueError):
    """炼制规则或请求不成立。"""


@dataclass(frozen=True)
class SectFacility:
    facility_type: Literal["炼器", "炼丹", "炼阵"]
    name: str
    scope: str
    supported_grades: tuple[str, ...]


@dataclass(frozen=True)
class FacilityPermission:
    role: str
    personal_materials: bool
    sect_materials: bool
    sacred_grade: bool
    grant_products: bool


@dataclass(frozen=True)
class SectFacilityStatus:
    initialized: bool
    facilities: tuple[SectFacility, ...]
    roles: tuple[str, ...]


@dataclass(frozen=True)
class SectFacilityEntry:
    content_id: str
    name: str
    detail: str
    available: bool


@dataclass(frozen=True)
class SectFacilityPage:
    facility: SectFacility
    role: str
    material_source: str
    spirit_stones: int
    section: str
    entries: tuple[SectFacilityEntry, ...]
    page: int = 1
    page_count: int = 1


@dataclass(frozen=True)
class SectForgingPreview:
    facility: SectFacility
    role: str
    material_source: str
    spirit_stones: int
    spirit_stone_cost: int
    assessment: ForgingAssessment


@dataclass(frozen=True)
class SectAlchemyPreview:
    facility: SectFacility
    role: str
    material_source: str
    spirit_stones: int
    spirit_stone_cost: int
    assessment: AlchemyAssessment


@dataclass(frozen=True)
class SectFormationPreview:
    facility: SectFacility
    role: str
    material_source: str
    spirit_stones: int
    spirit_stone_cost: int
    assessment: FormationAssessment


@dataclass(frozen=True)
class SectCraftResult:
    facility: SectFacility
    material_source: str
    product_id: str
    product_name: str
    grade_or_stage: str
    destination: str
    spirit_stone_cost: int
    spirit_stones_after: int
    replayed: bool


__all__ = [
    "FacilityPermission",
    "SectAlchemyPreview",
    "SectCraftResult",
    "SectFacility",
    "SectFacilityEntry",
    "SectFacilityError",
    "SectFacilityPage",
    "SectFacilityStatus",
    "SectForgingPreview",
    "SectFormationPreview",
]
