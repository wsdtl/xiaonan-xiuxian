"""道侣核心微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from game.core.database import StateMutation
from game.core.medicine import PreparedBattleMedicine


class CompanionError(RuntimeError):
    """道侣定义或玩家关系无法完成请求。"""


class CompanionNotFoundError(CompanionError, ValueError):
    """名称或编号没有对应的正式道侣。"""


class CompanionStateError(CompanionError):
    """玩家保存的道侣状态不符合当前契约。"""


class CompanionInvitationError(CompanionError, ValueError):
    """当前关系不满足邀约条件。"""


class CompanionGiftError(CompanionError, ValueError):
    """目标物品不能作为该道侣的赠礼。"""


class CompanionFarewellError(CompanionError, ValueError):
    """当前同行事实不允许暂别目标道侣。"""


class CompanionCultivationError(CompanionError, ValueError):
    """当前同行道侣不能完成这次培养。"""


@dataclass(frozen=True)
class CompanionStatus:
    initialized: bool
    companion_count: int
    location_count: int


@dataclass(frozen=True)
class CompanionRules:
    base_affection_per_item: Decimal
    favorite_gift_multiplier: Decimal
    acceptable_gift_multiplier: Decimal
    active_limit: int
    invitation_affection: Decimal
    first_invitation_gender_relation: str
    check_gender_again: bool
    full_reward_affection: Decimal
    full_reward_lifetime_limit: int
    cultivation_slots: Mapping[str, int]
    automatic_medicine_default: bool


@dataclass(frozen=True)
class CompanionReward:
    item_id: str
    grade_id: str
    quantity: int


@dataclass(frozen=True)
class CompanionDialogue:
    daily: tuple[str, ...]
    preference: str
    accept_gift: tuple[str, ...]
    refuse_gift: tuple[str, ...]
    full_affection: str
    invitation: str
    farewell: str


@dataclass(frozen=True)
class CompanionDefinition:
    companion_id: str
    name: str
    gender: str
    title: str
    stance: str
    description: str
    location_name: str
    realm_id: str
    realm_name: str
    level: int
    interactable: bool
    favorite_pool_names: tuple[str, ...]
    favorite_item_ids: frozenset[str]
    acceptable_pool_names: tuple[str, ...]
    acceptable_item_ids: frozenset[str]
    reward: CompanionReward
    dialogue: CompanionDialogue
    fixed_build: Mapping[str, tuple[str, ...]]
    attribute_overrides: Mapping[str, int | float]
    weapon_name: str
    weapon_level: int
    weapon_experience: int
    weapon_laws: tuple[str | None, ...]


@dataclass(frozen=True)
class LocalCultivator:
    companion_id: str
    name: str
    gender: str
    title: str
    description: str
    realm_id: str
    realm_name: str
    level: int
    interactable: bool


@dataclass(frozen=True)
class CompanionRelation:
    companion_id: str
    current_affection: Decimal
    gift_totals: Mapping[str, int]
    first_full_at: str
    first_invited_at: str
    version: int


@dataclass(frozen=True)
class ActiveCompanion:
    companion_id: str
    version: int


@dataclass(frozen=True)
class CompanionInstance:
    companion_id: str
    realm_id: str
    level: int
    experience: int
    attributes: Mapping[str, int | float]
    cultivation: Mapping[str, tuple[str, ...]]
    weapon_name: str
    weapon_level: int
    weapon_experience: int
    weapon_laws: tuple[str, ...]
    breakthrough_records: tuple[Mapping[str, object], ...]
    version: int
    resources: Mapping[str, int | float]
    automatic_medicine: bool
    prepared_battle_medicine: PreparedBattleMedicine | None
    five_elements: Mapping[str, float] = MappingProxyType({"木": 20, "火": 20, "土": 20, "金": 20, "水": 20})


@dataclass(frozen=True)
class ActiveCompanionInstance:
    active: ActiveCompanion
    instance: CompanionInstance


@dataclass(frozen=True)
class CompanionGrowthPlan:
    companion_id: str
    level_before: int
    level_after: int
    weapon_level_before: int
    weapon_level_after: int
    operations: tuple[StateMutation, ...]


@dataclass(frozen=True)
class CompanionRetreatPlan:
    companion_id: str
    experience_gained: int
    level_before: int
    level_after: int
    health: float
    spirit: float
    operation: StateMutation


@dataclass(frozen=True)
class CompanionBreakthroughPlan:
    companion_id: str
    realm_before: str
    realm_after: str
    realm_name_after: str
    medicine_id: str
    operations: tuple[StateMutation, ...]


@dataclass(frozen=True)
class CompanionBuildResetPlan:
    companion_id: str
    category: str
    content_ids: tuple[str, ...]
    operations: tuple[StateMutation, ...]


@dataclass(frozen=True)
class CompanionBreakthroughCorrectionPlan:
    companion_id: str
    target_realm: str
    source_medicine_id: str
    attributes: tuple[tuple[str, int | float], ...]
    operations: tuple[StateMutation, ...]


@dataclass(frozen=True)
class CompanionLawPlan:
    companion_id: str
    slot: int
    law_id: str
    law_name: str
    replaced_law_id: str
    operations: tuple[StateMutation, ...]


@dataclass(frozen=True)
class CompanionBattlePlan:
    companion_id: str
    health: float
    spirit: float
    weapon_experience_gained: int
    operation: StateMutation


@dataclass(frozen=True)
class CompanionMedicineSettingPlan:
    companion_id: str
    enabled: bool
    operations: tuple[StateMutation, ...]


@dataclass(frozen=True)
class CompanionRecoveryPlan:
    companion_id: str
    resource: str
    before: float
    after: float
    recovered: float
    operations: tuple[StateMutation, ...]


@dataclass(frozen=True)
class CompanionBattleMedicinePlan:
    companion_id: str
    before: PreparedBattleMedicine | None
    after: PreparedBattleMedicine | None
    operations: tuple[StateMutation, ...]


@dataclass(frozen=True)
class CompanionGiftPlan:
    relation_before: CompanionRelation
    relation_after: CompanionRelation
    first_full: bool
    operation: StateMutation


@dataclass(frozen=True)
class CompanionCultivationResetPlan:
    companion_id: str
    realm_before: str
    realm_after: str
    realm_name_after: str
    level_before: int
    level_after: int
    operation: StateMutation
    active_guard: StateMutation


@dataclass(frozen=True)
class CompanionSeverancePlan:
    companion_id: str
    affection_before: Decimal
    operations: tuple[StateMutation, ...]


@dataclass(frozen=True)
class CompanionInvitationPlan:
    relation: CompanionRelation
    instance: CompanionInstance
    first_invitation: bool
    already_active: bool
    operations: tuple[StateMutation, ...]


@dataclass(frozen=True)
class CompanionFarewellPlan:
    companion_id: str
    operation: StateMutation


@dataclass(frozen=True)
class CompanionBreakthroughPreview:
    """「当前同行道侣能不能突破、下一境界是什么」的只读预览。

    口径与 `CompanionService.plan_breakthrough` 的校验逐条一致；不能突破时给原因（带道侣名）。
    """

    companion_id: str
    name: str
    realm_id: str
    realm_name: str
    level: int
    maximum_level: int
    next_realm_id: str = ""
    next_realm_name: str = ""
    can_breakthrough: bool = False
    reason: str = ""


__all__ = [
    "ActiveCompanion",
    "ActiveCompanionInstance",
    "CompanionBattleMedicinePlan",
    "CompanionBattlePlan",
    "CompanionBreakthroughCorrectionPlan",
    "CompanionBreakthroughPlan",
    "CompanionBreakthroughPreview",
    "CompanionBuildResetPlan",
    "CompanionCultivationError",
    "CompanionCultivationResetPlan",
    "CompanionDefinition",
    "CompanionDialogue",
    "CompanionError",
    "CompanionFarewellError",
    "CompanionFarewellPlan",
    "CompanionGiftError",
    "CompanionGiftPlan",
    "CompanionGrowthPlan",
    "CompanionInstance",
    "CompanionInvitationError",
    "CompanionInvitationPlan",
    "CompanionLawPlan",
    "CompanionMedicineSettingPlan",
    "CompanionNotFoundError",
    "CompanionRecoveryPlan",
    "CompanionRelation",
    "CompanionRetreatPlan",
    "CompanionReward",
    "CompanionRules",
    "CompanionSeverancePlan",
    "CompanionStateError",
    "CompanionStatus",
    "LocalCultivator",
]
