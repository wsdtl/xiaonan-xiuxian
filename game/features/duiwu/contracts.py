"""队伍玩法微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class TeamFeatureError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class TeamCopy:
    text: Mapping[str, Mapping[str, str]]


@dataclass(frozen=True)
class TeamAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class TeamMemberView:
    user_id: str
    name: str
    role: str


@dataclass(frozen=True)
class TeamInvitationView:
    inviter_name: str
    remaining_minutes: int


@dataclass(frozen=True)
class TeamPage:
    page: str
    maximum_players: int
    members: tuple[TeamMemberView, ...] = ()
    invitation: TeamInvitationView | None = None


@dataclass(frozen=True)
class TeamOperationResult:
    action: str
    target_name: str
    page: TeamPage


@dataclass(frozen=True)
class TeamEntry:
    """一次队伍根命令的结果；分支与参数合规由玩法判定。"""

    kind: str
    page: TeamPage | None = None
    operation: TeamOperationResult | None = None


__all__ = [
    "TeamAction",
    "TeamCopy",
    "TeamEntry",
    "TeamFeatureError",
    "TeamInvitationView",
    "TeamMemberView",
    "TeamOperationResult",
    "TeamPage",
]
