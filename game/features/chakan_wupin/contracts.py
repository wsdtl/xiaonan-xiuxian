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
    #: 由能力树现算的规则正文。渲染器属于战斗核心，本层代为取得后交给命令层，
    #: 命令层因此不必导入核心服务（见 `微服务边界规范.md`「依赖方向」）。
    rendered: tuple[str, ...] = ()


__all__ = ["ItemInspectionResult"]
