"""统一使用入口的稳定契约：档案、计划、结果与端口。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass


class UseError(ValueError):
    """使用指称不合法，或当前档案不能执行。"""


@dataclass(frozen=True)
class UseAction:
    label: str
    command: str


@dataclass(frozen=True)
class UseProfile:
    prefix: str
    mode: str
    port: str = ""
    position: str = "无"
    candidates: tuple[str, ...] = ()
    default: str = ""
    grade: str = "可选"
    render_key: str = ""
    title: str = ""
    message: str = ""
    actions: tuple[UseAction, ...] = ()


@dataclass(frozen=True)
class UseRequest:
    user_id: str
    request_id: str
    item_id: str
    name: str = ""
    grade: str = ""
    treasure: str = ""
    target: str = ""
    position: int = 0


@dataclass(frozen=True)
class UseCandidate:
    value: str
    label: str
    kind: str


@dataclass(frozen=True)
class UseDescription:
    display: str
    position_kind: str
    candidates: tuple[UseCandidate, ...] = ()
    default: str = ""


@dataclass(frozen=True)
class UsePlan:
    request: UseRequest
    profile: UseProfile
    description: UseDescription


@dataclass(frozen=True)
class UseRedirect:
    title: str
    message: str
    actions: tuple[UseAction, ...] = ()


@dataclass(frozen=True)
class UseOutcome:
    render_key: str
    result: object


@dataclass(frozen=True)
class UsePort:
    describe: Callable[[UseRequest], Awaitable[UseDescription]]
    execute: Callable[[UseRequest], Awaitable[object]]


__all__ = [
    "UseAction",
    "UseCandidate",
    "UseDescription",
    "UseError",
    "UseOutcome",
    "UsePlan",
    "UsePort",
    "UseProfile",
    "UseRedirect",
    "UseRequest",
]
