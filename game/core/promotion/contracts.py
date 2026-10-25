"""升阶规则的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.database import StateMutation


class PromotionError(ValueError):
    """升阶请求无法完成。"""


class PromotionUnavailableError(PromotionError):
    """升阶规则尚未就绪。"""


@dataclass(frozen=True)
class MaterialRequirement:
    """一条炼制材料要求：类别、可指定编号、数量、最低品级。"""

    category: str
    item_id: str
    quantity: int
    minimum_grade_id: str


@dataclass(frozen=True)
class UpgradeLine:
    """一条要执行的升阶：来源品级 → 目标品级。"""

    item_id: str
    item_name: str
    source_grade_id: str
    source_grade_name: str
    target_grade_id: str
    target_grade_name: str
    quantity: int
    unit_cost: int
    total_cost: int


@dataclass(frozen=True)
class UpgradePlan:
    lines: tuple[UpgradeLine, ...]
    total_cost: int
    spirit_stone_before: int
    spirit_stone_after: int
    affordable: bool
    operations: tuple[StateMutation, ...]


@dataclass(frozen=True)
class MaterialPlan:
    lines: tuple[UpgradeLine, ...]
    total_cost: int
    spirit_stone_before: int
    spirit_stone_after: int
    affordable: bool
    missing: tuple[MaterialRequirement, ...]
    satisfiable: bool


@dataclass(frozen=True)
class PromotionStatus:
    initialized: bool
    allowed_categories: tuple[str, ...]
    max_grade_id: str
    batch_limit: int


__all__ = [
    "MaterialPlan",
    "MaterialRequirement",
    "PromotionError",
    "PromotionStatus",
    "PromotionUnavailableError",
    "UpgradeLine",
    "UpgradePlan",
]
