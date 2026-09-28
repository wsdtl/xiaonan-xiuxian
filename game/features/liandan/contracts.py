"""炼丹玩法微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from game.core.alchemy import (
    AlchemyOverview,
    AlchemyPreview,
    AlchemyRecipeList,
    AlchemyResult,
)
from game.core.alchemy import AlchemyMaterial


class AlchemyFeatureError(RuntimeError):
    """炼丹玩法无法完成请求。"""


@dataclass(frozen=True)
class AlchemyAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class AlchemyCopy:
    text: Mapping[str, Mapping[str, str]]


__all__ = [
    "AlchemyAction",
    "AlchemyCopy",
    "AlchemyFeatureError",
    "AlchemyOverview",
    "AlchemyPreview",
    "AlchemyRecipeList",
    "AlchemyResult",
    "AlchemyMaterial",
]
