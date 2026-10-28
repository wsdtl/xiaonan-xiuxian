"""宗门同行玩法微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class SectFollowFeatureError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SectFollowMemberView:
    user_id: str
    name: str
    role: str


@dataclass(frozen=True)
class SectFollowPage:
    page: str
    sect_name: str
    leader_name: str = ""
    members: tuple[SectFollowMemberView, ...] = ()
    maximum_members: int = 0


@dataclass(frozen=True)
class SectFollowResult:
    action: str
    target_name: str
    page: SectFollowPage


@dataclass(frozen=True)
class SectFollowAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class SectFollowCopy:
    text: Mapping[str, Mapping[str, str]]


@dataclass(frozen=True)
class SectFollowEntry:
    """一次宗门同行根命令的结果；分支与参数合规由玩法判定。"""

    kind: str
    page: SectFollowPage | None = None
    result: SectFollowResult | None = None


__all__ = [
    "SectFollowAction",
    "SectFollowCopy",
    "SectFollowEntry",
    "SectFollowFeatureError",
    "SectFollowMemberView",
    "SectFollowPage",
    "SectFollowResult",
]
