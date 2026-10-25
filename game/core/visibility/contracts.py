"""网页可见性开关的稳定契约。"""

from __future__ import annotations

from dataclasses import dataclass


class VisibilityError(RuntimeError):
    """网页可见性开关无法完成。"""


class VisibilityConflictError(VisibilityError):
    """请求编号已经用于其他操作。"""


@dataclass(frozen=True)
class VisibilityScope:
    user_id: str
    name: str


__all__ = ["VisibilityConflictError", "VisibilityError", "VisibilityScope"]
