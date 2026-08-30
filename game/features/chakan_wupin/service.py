"""查看正式编号实体的玩法编排。"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence

from game.core.item_catalog import (
    ItemCatalogService,
    ItemDetail,
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
                detail=(detail := self._catalog.inspect_entity(normalized)),
                related_details=self._related_details(detail),
            )
        except ItemNameAmbiguousError as exc:
            return ItemInspectionResult(normalized, candidates=exc.candidates)
        except ItemNotFoundError:
            return ItemInspectionResult(normalized)

    def _related_details(self, detail: ItemDetail) -> tuple[ItemDetail, ...]:
        """解析详情实际引用的编号实体，供玩家页显示名称和真实效果。"""

        pending = list(_entity_references(detail.fields))
        resolved: list[ItemDetail] = []
        seen: set[str] = {detail.item_id}
        while pending:
            entity_id = pending.pop(0)
            if entity_id in seen:
                continue
            seen.add(entity_id)
            try:
                related = self._catalog.inspect_entity(entity_id)
            except ItemNotFoundError:
                continue
            resolved.append(related)
            pending.extend(_entity_references(related.fields))
        return tuple(resolved)


def _entity_references(value: object) -> Iterator[str]:
    if isinstance(value, Mapping):
        for child in value.values():
            yield from _entity_references(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            yield from _entity_references(child)
    elif isinstance(value, str) and value.isdigit() and len(value) == 6:
        yield value


__all__ = ["ItemInspectionFeature"]
