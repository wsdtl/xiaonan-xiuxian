"""升阶玩法公共契约。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.promotion import MaterialPlan, UpgradeLine


class ShengjieError(ValueError):
    """升阶玩法无法完成。"""


@dataclass(frozen=True)
class ShengjieResult:
    item_id: str
    item_name: str
    source_grade_id: str
    source_grade_name: str
    target_grade_id: str
    target_grade_name: str
    quantity: int
    unit_cost: int
    total_cost: int
    spirit_stone_before: int
    spirit_stone_after: int
    replayed: bool


@dataclass(frozen=True)
class CraftingPlan:
    kind: str
    name: str
    plan: MaterialPlan
    craft_command: str


@dataclass(frozen=True)
class MaterialPlanView:
    category: str
    target_grade_id: str
    target_grade_name: str
    plan: MaterialPlan


__all__ = [
    "CraftingPlan",
    "MaterialPlanView",
    "ShengjieError",
    "ShengjieResult",
    "UpgradeLine",
]
