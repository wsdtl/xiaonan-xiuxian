"""查看正式编号实体的公共结果。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from game.core.item_catalog import ItemDetail, ItemSummary


@dataclass(frozen=True)
class HeldGrade:
    """执行者手里那份实例的品级。

    品级是**实例级**事实（`编号.json` 的「编号不承载品级」），实体本身没有品级，
    所以查看页要显示品级，只能看执行者自己持有的是哪一份。
    """

    grade_id: str
    name: str
    multiplier: float
    quantity: int = 1


@dataclass(frozen=True)
class ItemInspectionResult:
    query: str
    detail: ItemDetail | None = None
    candidates: tuple[ItemSummary, ...] = ()
    related_details: tuple[ItemDetail, ...] = ()
    #: 由能力树现算的规则正文。渲染器属于战斗核心，本层代为取得后交给命令层，
    #: 命令层因此不必导入核心服务（见 `微服务边界规范.md`「依赖方向」）。
    rendered: tuple[str, ...] = ()
    #: 执行者持有该编号的品级（可能多份不同品级）；空表示没持有。
    held_grades: tuple[HeldGrade, ...] = ()
    #: 敌人条目页的遮罩词（来自 角色/展示/敌人.json）：配置里没有的答案就不假装知道。
    mask_text: str = ""


@dataclass(frozen=True)
class BaikeEntry:
    """百科总表里的一条：编号、名称与来源标签。"""

    entity_id: str
    name: str
    source: str


@dataclass(frozen=True)
class BaikePrefixRow:
    """登记表里的一行前缀：主体、类别与该前缀下的实际条数。"""

    prefix: str
    subject: str
    category: str
    count: int


@dataclass(frozen=True)
class BaikeCatalog:
    """百科总表：全部条目 + 按登记表数出来的前缀行。"""

    entries: tuple[BaikeEntry, ...]
    prefix_rows: tuple[BaikePrefixRow, ...]


@dataclass(frozen=True)
class BaikeReference:
    """实体字段里指向另一条实体的编号式引用。"""

    field: str
    entity_id: str
    name: str


@dataclass(frozen=True)
class BaikeDetail:
    """单条实体的详情：名称、来源、原始字段与引用图。"""

    entity_id: str
    name: str
    source: str
    number_category: str
    fields: Mapping[str, object]
    references: tuple[BaikeReference, ...] = ()

__all__ = [
    "BaikeCatalog",
    "BaikeDetail",
    "BaikeEntry",
    "BaikePrefixRow",
    "BaikeReference",
    "HeldGrade",
    "ItemInspectionResult",
    "ItemDetail",
]
