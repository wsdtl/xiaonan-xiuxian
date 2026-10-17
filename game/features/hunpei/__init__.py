"""婚配（生育）玩法微服务。"""
from __future__ import annotations

from .contracts import (
    BirthAsk,
    BirthDeniedError,
    BirthRequestView,
    BirthRespond,
    BirthResult,
    BirthView,
    HunpeiCopy,
    HunpeiError,
    Newborn,
)
from .service import HunpeiFeature
from .store import BirthRequestRow, BirthRequestStore

__all__ = [
    "BirthAsk",
    "BirthDeniedError",
    "BirthRequestRow",
    "BirthRequestStore",
    "BirthRequestView",
    "BirthRespond",
    "BirthResult",
    "BirthView",
    "HunpeiCopy",
    "HunpeiError",
    "HunpeiFeature",
    "Newborn",
]
