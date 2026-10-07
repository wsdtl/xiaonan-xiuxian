"""人物培养玩法的稳定请求与结果。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.character import CharacterProfile
from game.core.innate_treasure import InnateTreasureActivation


class CharacterCultivationFeatureError(ValueError):
    """人物培养输入或当前状态不允许完成请求。"""


class CharacterCultivationConflictError(RuntimeError):
    """人物培养期间相关状态已经变化。"""


@dataclass(frozen=True)
class CharacterEquipRequest:
    user_id: str
    request_id: str
    category: str
    content: str
    grade: str
    slot: int


@dataclass(frozen=True)
class CharacterBreakthroughRequest:
    user_id: str
    request_id: str
    medicine: str


@dataclass(frozen=True)
class CharacterLawRequest:
    user_id: str
    request_id: str
    law: str
    slot: int


@dataclass(frozen=True)
class CharacterCultivationView:
    profile: CharacterProfile
    next_experience: int
    weapon_next_experience: int


@dataclass(frozen=True)
class CharacterEquipResult:
    profile: CharacterProfile
    category: str
    slot: int
    content_name: str
    replayed: bool
    treasure_activation: InnateTreasureActivation | None = None


@dataclass(frozen=True)
class CharacterBreakthroughResult:
    profile: CharacterProfile
    medicine_name: str
    #: 消耗的那份丹药的品级。品级是实例级事实，消耗的是具体哪一品必须露出来。
    medicine_grade: str
    realm_name: str
    replayed: bool
    treasure_activation: InnateTreasureActivation | None = None


@dataclass(frozen=True)
class CharacterLawResult:
    profile: CharacterProfile
    law_name: str
    slot: int
    replayed: bool


__all__ = [
    "CharacterBreakthroughRequest",
    "CharacterBreakthroughResult",
    "CharacterCultivationConflictError",
    "CharacterCultivationFeatureError",
    "CharacterCultivationView",
    "CharacterEquipRequest",
    "CharacterEquipResult",
    "CharacterLawRequest",
    "CharacterLawResult",
]
