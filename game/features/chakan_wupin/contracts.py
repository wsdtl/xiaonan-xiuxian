"""查看正式编号实体的公共结果。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.item_catalog import ItemDetail, ItemSummary


@dataclass(frozen=True)
class ItemInspectionResult:
    query: str
    detail: ItemDetail | None = None
    candidates: tuple[ItemSummary, ...] = ()
    related_details: tuple[ItemDetail, ...] = ()


__all__ = ["ItemInspectionResult"]
