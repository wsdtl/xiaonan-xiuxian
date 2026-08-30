"""纳戒玩法的稳定只读结果。"""

from __future__ import annotations

from dataclasses import dataclass


class NajieQueryError(ValueError):
    """纳戒分类或页码查询无效。"""


class NajieStateError(RuntimeError):
    """玩家资产暂时无法形成合法纳戒视图。"""


@dataclass(frozen=True)
class NajieEntry:
    category: str
    content_id: str
    name: str
    grade_id: str
    grade_name: str
    quantity: int
    equipped_slots: tuple[str, ...]
    material_total: int | None


@dataclass(frozen=True)
class NajieSubcategorySummary:
    name: str
    entry_count: int
    total_quantity: int


@dataclass(frozen=True)
class NajieCategorySummary:
    name: str
    icon: str
    entry_count: int
    total_quantity: int
    subcategories: tuple[NajieSubcategorySummary, ...]


@dataclass(frozen=True)
class NajieHome:
    categories: tuple[NajieCategorySummary, ...]


@dataclass(frozen=True)
class NajieCategoryView:
    category: NajieCategorySummary


@dataclass(frozen=True)
class NajiePage:
    category: str
    subcategory: str
    icon: str
    page: int
    total_pages: int
    entry_count: int
    total_quantity: int
    start_index: int
    end_index: int
    entries: tuple[NajieEntry, ...]


__all__ = [
    "NajieCategorySummary",
    "NajieCategoryView",
    "NajieEntry",
    "NajieHome",
    "NajiePage",
    "NajieQueryError",
    "NajieStateError",
    "NajieSubcategorySummary",
]
