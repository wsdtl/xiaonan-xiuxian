"""炼器玩法微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from game.core.forging import (
    ForgingLawList,
    ForgingOverview,
    ForgingPreview,
    ForgingResult,
)
from game.core.forging import ForgingMaterial


class ForgingFeatureError(RuntimeError):
    """炼器玩法无法完成请求。"""


@dataclass(frozen=True)
class ForgingAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class ForgingCopy:
    text: Mapping[str, Mapping[str, str]]


__all__ = [
    "ForgingAction",
    "ForgingCopy",
    "ForgingFeatureError",
    "ForgingLawList",
    "ForgingOverview",
    "ForgingPreview",
    "ForgingResult",
    "ForgingMaterial",
]
