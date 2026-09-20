"""人物与道侣共用的修士成长计算契约。"""

from __future__ import annotations

from dataclasses import dataclass


class GrowthError(ValueError):
    """成长参数或正式规则无法完成计算。"""


@dataclass(frozen=True)
class GrowthStatus:
    initialized: bool
    realm_count: int
    maximum_level: int


@dataclass(frozen=True)
class RealmDefinition:
    realm_id: str
    name: str
    minimum_level: int
    maximum_level: int
    next_realm_id: str = ""
    #: 这一境界的自然寿数上限（年）。种族用 `寿元系数` 乘它：仙族活得久、诡异活得短。
    lifespan: int = 0


@dataclass(frozen=True)
class ExperienceAdvance:
    level_before: int
    level_after: int
    experience_before: int
    experience_after: int
    experience_gained: int
    levels_gained: int
    capped: bool


@dataclass(frozen=True)
class RandomCultivationBuild:
    seed: int
    techniques: tuple[str, ...]
    intents: tuple[str, ...]
    qi_patterns: tuple[str, ...]


@dataclass(frozen=True)
class CultivationCategoryBuild:
    category: str
    content_ids: tuple[str, ...]


__all__ = [
    "CultivationCategoryBuild",
    "ExperienceAdvance",
    "GrowthError",
    "GrowthStatus",
    "RandomCultivationBuild",
    "RealmDefinition",
]
