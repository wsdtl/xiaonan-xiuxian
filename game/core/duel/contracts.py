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
    challenge_id: str
    #: 发起者编号。战报页面要按「发起者 + 切磋编号」取存档（切磋结果挂在发起者名下），
    #: 所以结果本身得带着它（第 121 轮：试玩发现切磋战报没有入口）。
    owner: str
    winner: str
    user_participants: tuple[str, ...]
    target_participants: tuple[str, ...]
    actions: int
    events: int
    replayed: bool


__all__ = ["DuelChallenge", "DuelError", "DuelResult", "DuelStartCommand"]
