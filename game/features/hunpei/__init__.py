"""婚配（生育）玩法微服务。"""

from .contracts import (
    BirthDeniedError,
    BirthResult,
    BirthView,
    HunpeiCopy,
    HunpeiError,
    Newborn,
)
from .service import HunpeiFeature

__all__ = [
    "BirthDeniedError",
    "BirthResult",
    "BirthView",
    "HunpeiCopy",
    "HunpeiError",
    "HunpeiFeature",
    "Newborn",
]
