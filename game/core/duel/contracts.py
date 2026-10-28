from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class DuelError(RuntimeError):
    """切磋请求无法完成。"""


@dataclass(frozen=True)
class DuelStartCommand:
    user_id: str
    target_user_id: str
    request_id: str
    created_at: datetime | None = None


@dataclass(frozen=True)
class DuelChallenge:
    challenge_id: str
    user_id: str
    target_user_id: str
    user_participants: tuple[str, ...]
    target_participants: tuple[str, ...]
    expires_at: datetime
    replayed: bool


@dataclass(frozen=True)
class DuelResult:
    #: 本场战报编号；结算卡直接给一次链接，之后历史走 `战报`。
    report_id: str
    #: 发起者编号：切磋记录挂在发起者名下，所以结果本身要带着它。
    owner: str
    winner: str
    user_participants: tuple[str, ...]
    target_participants: tuple[str, ...]
    actions: int
    events: int
    replayed: bool


__all__ = ["DuelChallenge", "DuelError", "DuelResult", "DuelStartCommand"]
