"""正式编号实体查询微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


class ItemCatalogError(ValueError):
    """实体查询参数或 JSON 定义不满足查询契约。"""


class ItemNotFoundError(ItemCatalogError):
    """编号或名称没有对应的正式实体。"""


class ItemNameAmbiguousError(ItemCatalogError):
    """名称对应多个实体，调用方必须让用户选择。"""

    def __init__(self, name: str, candidates: tuple[ItemSummary, ...]) -> None:
        self.name = name
        self.candidates = candidates
        super().__init__(f"实体名称不唯一：{name}")


@dataclass(frozen=True)
class ItemSummary:
    item_id: str
    category: str
    name: str
    section: str = "物品"

    @property
    def entity_id(self) -> str:
        return self.item_id


@dataclass(frozen=True)
class ItemDetail:
    item_id: str
    category: str
    name: str
    description: str
    fields: Mapping[str, Any] = field(default_factory=dict)
    section: str = "物品"

    @property
    def entity_id(self) -> str:
        return self.item_id


@dataclass(frozen=True)
class ItemCatalogStatus:
    initialized: bool
    item_count: int
    category_counts: Mapping[str, int] = field(default_factory=dict)


__all__ = [
    "ItemCatalogError",
    "ItemCatalogStatus",
    "ItemDetail",
    "ItemNameAmbiguousError",
    "ItemNotFoundError",
    "ItemSummary",
]
