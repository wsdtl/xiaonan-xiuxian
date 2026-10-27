"""人物培养玩法的稳定请求与结果。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.character import CharacterBreakthroughPreview, CharacterProfile
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
class CharacterUseTarget:
    """一件可“使用”的构筑：编号、显示名、类别与可选位置。"""

    item_id: str
    name: str
    category: str
    slots: tuple[int, ...]


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
class BreakthroughCandidate:
    """一颗候选突破丹：编号是句柄、名称只作显示，永久属性照数据原样带出。"""

    medicine_id: str
    name: str
    permanent: tuple[tuple[str, int | float], ...] = ()


@dataclass(frozen=True)
class BreakthroughOffer:
    """「能不能突破、下一境界是什么、本境界有哪些丹可用」——查看页与失败卡共用一份。"""

    preview: CharacterBreakthroughPreview
    candidates: tuple[BreakthroughCandidate, ...] = ()


@dataclass(frozen=True)
class CharacterCultivationView:
    profile: CharacterProfile
    next_experience: int
    weapon_next_experience: int
    #: 突破预览与候选丹药；没有下一境界时也在，用 `preview.reason` 说话。
    breakthrough: BreakthroughOffer | None = None


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




@dataclass(frozen=True)
class PeiyangAction:
    """培养回执上的动作，字段名与 CommandAction 契约一致。"""

    action_id: str
    label: str
    command: str
    behavior: str
    style: str


__all__ = [
    "BreakthroughCandidate",
    "BreakthroughOffer",
    "CharacterBreakthroughRequest",
    "CharacterBreakthroughResult",
    "CharacterCultivationConflictError",
    "CharacterCultivationFeatureError",
    "CharacterCultivationView",
    "CharacterEquipRequest",
    "CharacterEquipResult",
    "CharacterLawRequest",
    "CharacterLawResult",
    "CharacterUseTarget",
]
