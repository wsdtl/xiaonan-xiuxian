"""炼丹规则与炼制事务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from game.core.innate_treasure import InnateTreasureActivation


class AlchemyError(ValueError):
    """炼丹规则或请求无法完成。"""


class AlchemyUnavailableError(AlchemyError):
    """当前位置没有丹师主持炼制。"""


class AlchemyMaterialError(AlchemyError):
    """纳戒材料不足。"""


class AlchemyConflictError(AlchemyError):
    """提交时库存或请求状态发生冲突。"""


@dataclass(frozen=True)
class AlchemyStatus:
    initialized: bool
    recipe_count: int
    medicine_count: int
    method_count: int
    alchemist_count: int
    beast_treasure_count: int
    herb_count: int


@dataclass(frozen=True)
class Alchemist:
    alchemist_id: str
    name: str
    location_name: str
    title: str
    furnace_name: str
    speech_style: str
    speech: Mapping[str, str]


@dataclass(frozen=True)
class AlchemyRecipe:
    recipe_id: str
    name: str
    category: str
    difficulty: int
    method: str
    medicine_id: str
    medicine_name: str
    materials: tuple[Mapping[str, object], ...] = ()
    no_grade: bool = False
    plight: str = ""


@dataclass(frozen=True)
class AlchemyMaterial:
    item_id: str
    name: str
    grade_id: str
    grade_name: str
    role: str
    trait: str
    relation: str
    quantity: int


@dataclass(frozen=True)
class AlchemyMissingMaterial:
    role: str
    trait: str
    quantity: int


@dataclass(frozen=True)
class AlchemyAssessment:
    recipe: AlchemyRecipe
    medicine_grade_id: str
    medicine_grade_name: str
    beast_material: AlchemyMaterial | None
    herb_materials: tuple[AlchemyMaterial, ...]
    missing_materials: tuple[AlchemyMissingMaterial, ...]
    secondary_substitutions: int
    secondary_substitution_limit: int
    can_refine: bool


@dataclass(frozen=True)
class AlchemyPreview:
    user_id: str
    location_name: str
    alchemist: Alchemist
    recipe: AlchemyRecipe
    medicine_grade_id: str
    medicine_grade_name: str
    beast_material: AlchemyMaterial | None
    herb_materials: tuple[AlchemyMaterial, ...]
    missing_materials: tuple[AlchemyMissingMaterial, ...]
    secondary_substitutions: int
    secondary_substitution_limit: int
    can_refine: bool


@dataclass(frozen=True)
class AlchemyRecipeEntry:
    recipe: AlchemyRecipe
    can_refine: bool
    missing_count: int


@dataclass(frozen=True)
class AlchemyOverview:
    user_id: str
    location_name: str
    alchemist: Alchemist
    category_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class AlchemyRecipeList:
    user_id: str
    location_name: str
    alchemist: Alchemist
    category: str
    entries: tuple[AlchemyRecipeEntry, ...]
    page: int
    page_count: int


@dataclass(frozen=True)
class AlchemyResult:
    preview: AlchemyPreview
    quantity_before: int
    quantity_after: int
    replayed: bool
    treasure_activation: InnateTreasureActivation | None = None


__all__ = [
    "Alchemist",
    "AlchemyAssessment",
    "AlchemyConflictError",
    "AlchemyError",
    "AlchemyMaterial",
    "AlchemyMaterialError",
    "AlchemyMissingMaterial",
    "AlchemyOverview",
    "AlchemyPreview",
    "AlchemyRecipe",
    "AlchemyRecipeEntry",
    "AlchemyRecipeList",
    "AlchemyResult",
    "AlchemyStatus",
    "AlchemyUnavailableError",
]
