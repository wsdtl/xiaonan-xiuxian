"""查看正式编号实体的公共结果。"""

from __future__ import annotations

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


__all__ = [
    "HeldGrade",
    "ItemInspectionResult",
    "ItemDetail",
]
