"""意境特性微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass


class YijingError(ValueError):
    """意境请求不符合当前人物状态（没选路、境界不够、道行不足、已满九阶）。"""


class YijingConflictError(RuntimeError):
    """同一条请求编号已经用于别的操作。"""


@dataclass(frozen=True)
class YijingView:
    """命令层渲染用的一份视图：路、阶、道行与下一阶还差多少。"""

    content_id: str
    name: str
    display: str
    tier: int
    points: int
    cap: int
    next_cost: int
    missing: int
    routes: tuple[tuple[str, str], ...]


__all__ = ["YijingConflictError", "YijingError", "YijingView"]
