"""宗门战核心的稳定公共契约。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class SectWarError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

@dataclass(frozen=True)
class SectWarStatus:
    initialized: bool
    seconds: int
    maximum_participants: int

@dataclass(frozen=True)
class SectWarView:
    war_id: str
    attacker_sect_id: str
    defender_sect_id: str
    attacker_name: str
    defender_name: str
    status: str
    wager: int
    attacker_count: int = 0
    defender_count: int = 0
    ends_at: datetime | None = None
    winner: str = ""
    attacker_locked: bool = False
    defender_locked: bool = False
    report_id: str = ""


@dataclass(frozen=True)
class SectWarHistoryPage:
    page: int
    page_count: int
    total: int
    entries: tuple[SectWarView, ...]

__all__ = [
    "SectWarError",
    "SectWarHistoryPage",
    "SectWarStatus",
    "SectWarView",
]
