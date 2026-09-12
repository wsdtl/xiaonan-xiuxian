"""查看正式编号实体的玩法编排。"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence

from game.core.combat import render_body, render_listeners
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
                rendered=_rendered_lines(detail),
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


#: 正文由能力树现算的领域。构筑四类、丹药、战场环境走 `render_body`；
#: 伤势的战斗状态走 `render_listeners`。其余领域没有能力树，正文在命令层成形。
_ABILITY_TREE_SECTIONS = frozenset({"功法", "真意", "气机", "器律", "丹药", "战场环境"})


def _rendered_lines(detail: ItemDetail) -> tuple[str, ...]:
    """按领域把能力树渲染成规则正文。

    放在玩法层而不是命令层：渲染器是战斗核心的公共能力，而命令层不得导入核心服务。
    命令层只决定这些行**显示在哪**，不决定它们**怎么写**。
    """

    section = detail.section
    if section in _ABILITY_TREE_SECTIONS:
        return tuple(render_body(detail.fields)[0])
    if section == "伤势":
        state = detail.fields.get("战斗状态")
        if isinstance(state, Mapping):
            return tuple(render_listeners(state)[0])
    return ()


__all__ = ["ItemInspectionFeature"]
