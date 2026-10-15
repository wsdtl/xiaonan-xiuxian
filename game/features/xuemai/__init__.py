"""血脉玩法微服务。"""

from .contracts import (
    GenealogyCopy,
    GenealogyEntry,
    GenealogyQueryError,
    GenealogyView,
    SuccessionResult,
    XuemaiError,
)
from .service import XuemaiFeature

__all__ = [
    "GenealogyCopy",
    "GenealogyEntry",
    "GenealogyQueryError",
    "GenealogyView",
    "SuccessionResult",
    "XuemaiError",
    "XuemaiFeature",
]