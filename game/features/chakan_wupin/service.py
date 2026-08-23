"""查看正式编号实体的玩法编排。"""

from __future__ import annotations

from game.core.item_catalog import (
    ItemCatalogService,
    ItemNameAmbiguousError,
    ItemNotFoundError,
)

from .contracts import ItemInspectionResult


class ItemInspectionFeature:
    """把实体查询结果交给命令层，不携带命令或消息协议依赖。"""

    def __init__(self, catalog: ItemCatalogService) -> None:
        self._catalog = catalog
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("查看实体玩法微服务已经初始化")
        if not self._catalog.status().initialized:
            raise RuntimeError("实体查询微服务必须先于查看实体玩法启动")
        self._initialized = True

    def inspect(self, query: str) -> ItemInspectionResult:
        if not self._initialized:
            raise RuntimeError("查看实体玩法微服务尚未初始化")
        normalized = " ".join(str(query or "").split())
        try:
            return ItemInspectionResult(
                normalized,
                detail=self._catalog.inspect_entity(normalized),
            )
        except ItemNameAmbiguousError as exc:
            return ItemInspectionResult(normalized, candidates=exc.candidates)
        except ItemNotFoundError:
            return ItemInspectionResult(normalized)


__all__ = ["ItemInspectionFeature"]
