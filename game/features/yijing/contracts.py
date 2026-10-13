"""意境特性微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass


class YijingError(ValueError):
    """意境请求不符合当前人物状态（境界不够、道行不足、已满九阶）。"""


class YijingConflictError(RuntimeError):
    """同一条请求编号已经用于别的操作。"""


@dataclass(frozen=True)
class YijingRoute:
    """六条路里的一条在面板上的现状：未点过的一行阶为 0、展示串为空。"""

    content_id: str
    name: str
    tier: int
    display: str
    #: 点下一阶要多少道行、还差多少（已满或到境界上限时为 0）。
    next_cost: int
    missing: int


@dataclass(frozen=True)
class YijingView:
    """命令层渲染用的一份视图：**六条路各自的阶** ＋ 六路共享的道行 ＋ 当前境界给的阶上限。"""

    points: int
    cap: int
    routes: tuple[YijingRoute, ...]


__all__ = ["YijingConflictError", "YijingError", "YijingRoute", "YijingView"]
