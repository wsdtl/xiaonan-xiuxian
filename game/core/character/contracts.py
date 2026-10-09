"""角色核心微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from game.core.database import StateMutation
from game.core.medicine import PreparedBattleMedicine


class CharacterCreationError(RuntimeError):
    """角色创建无法完成。"""


class CharacterInputError(CharacterCreationError, ValueError):
    """创建输入不符合正式 JSON 规则。"""


class CharacterAlreadyExistsError(CharacterCreationError):
    """该用户已经拥有角色。"""


class CharacterNotFoundError(RuntimeError):
    """该用户尚未创建人物。"""


class CharacterStateError(RuntimeError):
    """已经保存的角色资产不符合当前正式规则。"""


class CharacterCultivationError(CharacterStateError, ValueError):
    """人物培养请求不符合当前人物、道藏或本命武器状态。"""


@dataclass(frozen=True)
class CharacterStatus:
    initialized: bool
    role_name: str
    gender_count: int
    initial_item_count: int


@dataclass(frozen=True)
class CharacterCreateCommand:
    user_id: str
    request_id: str
    name: str
    gender: str
    birth_xy: tuple[int, int]
    #: 种族（天生那一层）：留空表示用人物.json 的 `创建.初始种族`（基准族人族）。
    race: str = ""


@dataclass(frozen=True)
class CharacterCreationResult:
    user_id: str
    name: str
    gender: str
    realm_id: str
    realm_name: str
    birth_xy: tuple[int, int]
    initial_items: tuple[tuple[str, str, str, int], ...]
    replayed: bool
    race: str = ""


@dataclass(frozen=True)
class EquippedContent:
    category: str
    slot: int
    content_id: str
    name: str
    grade: str = ""
    grade_name: str = ""


@dataclass(frozen=True)
class WeaponProfile:
    name: str
    level: int
    experience: int
    attack: int | float
    stage: str
    open_law_slots: int
    equipped_laws: tuple[EquippedContent, ...]


@dataclass(frozen=True)
class InventorySummary:
    stack_count: int
    total_quantity: int


@dataclass(frozen=True)
class CharacterPublicProfile:
    user_id: str
    name: str
    gender: str
    realm_id: str
    realm_name: str
    level: int


@dataclass(frozen=True)
class CharacterProfile:
    user_id: str
    name: str
    gender: str
    character_type: str
    realm_id: str
    realm_name: str
    level: int
    experience: int
    spirit_stones: int
    sect_contribution: int
    automatic_medicine: bool
    prepared_battle_medicine: PreparedBattleMedicine | None
    attributes: tuple[tuple[str, int | float], ...]
    resources: tuple[tuple[str, int | float], ...]
    cultivation_slots: tuple[tuple[str, int], ...]
    equipped_content: tuple[EquippedContent, ...]
    weapon: WeaponProfile
    inventory: InventorySummary
    five_elements: Mapping[str, float]
    #: 种族（天生那一层）：人物面板与查看页据此显示，战斗快照据此挂天生锁定技。
    race: str = ""
    #: 寿元上限（年）：当前境界的寿元 × 种族的寿元系数。这一轮只算上限，不做衰老与寿终。
    lifespan: int = 0
    #: 当前年龄（展示用）：由状态里的「诞生」时间戳按比例推出来，永远钳在寿元上限之内。
    #: 设计口径——只作展示，没有衰老与寿终，所以「超过上限」根本不该出现，也不需要处理。
    age: int = 0


@dataclass(frozen=True)
class CharacterGrowthPlan:
    level_before: int
    level_after: int
    weapon_level_before: int
    weapon_level_after: int
    operations: tuple[StateMutation, ...]


@dataclass(frozen=True)
class CharacterAbsorptionPlan:
    experience_offered: int
    experience_accepted: int
    experience_discarded: int
    level_before: int
    level_after: int
    experience_after: int
    operation: StateMutation


@dataclass(frozen=True)
class CharacterRetreatPlan:
    experience_gained: int
    level_before: int
    level_after: int
    health: float
    spirit: float
    operation: StateMutation


@dataclass(frozen=True)
class CharacterAssemblyPlan:
    operations: tuple[StateMutation, ...]
    changed_slots: int


@dataclass(frozen=True)
class CharacterEquipPlan:
    category: str
    slot: int
    content_id: str
    content_name: str
    grade_id: str
    replaced_content_id: str
    replaced_grade_id: str
    operation: StateMutation
    reserve_operation: StateMutation | None


@dataclass(frozen=True)
class CharacterSpiritStonePlan:
    before: int
    after: int
    delta: int
    operation: StateMutation


@dataclass(frozen=True)
class CharacterContributionPlan:
    before: int
    after: int
    delta: int
    operation: StateMutation


@dataclass(frozen=True)
class CharacterTechniqueUpgradePlan:
    updated_slots: int
    operation: StateMutation | None


@dataclass(frozen=True)
class CharacterBreakthroughPlan:
    realm_before: str
    realm_after: str
    realm_name_after: str
    medicine_id: str
    permanent_attributes: tuple[tuple[str, int | float], ...]
    operation: StateMutation


@dataclass(frozen=True)
class CharacterBreakthroughCorrectionPlan:
    target_realm: str
    source_medicine_id: str
    attributes: tuple[tuple[str, int | float], ...]
    operation: StateMutation


@dataclass(frozen=True)
class CharacterGenderPlan:
    gender_before: str
    gender_after: str
    operation: StateMutation


@dataclass(frozen=True)
class CharacterLawPlan:
    slot: int
    law_id: str
    law_name: str
    replaced_law_id: str
    operation: StateMutation


@dataclass(frozen=True)
class CharacterBattlePlan:
    health: float
    spirit: float
    spirit_stones_delta: int
    weapon_experience_gained: int
    operations: tuple[StateMutation, ...]


@dataclass(frozen=True)
class CharacterMedicineSettingPlan:
    enabled: bool
    operation: StateMutation


@dataclass(frozen=True)
class CharacterRecoveryPlan:
    resource: str
    before: float
    after: float
    recovered: float
    operation: StateMutation


@dataclass(frozen=True)
class CharacterBattleMedicinePlan:
    before: PreparedBattleMedicine | None
    after: PreparedBattleMedicine | None
    operation: StateMutation


__all__ = [
    "CharacterAbsorptionPlan",
    "CharacterAlreadyExistsError",
    "CharacterBattleMedicinePlan",
    "CharacterBattlePlan",
    "CharacterBreakthroughCorrectionPlan",
    "CharacterBreakthroughPlan",
    "CharacterContributionPlan",
    "CharacterCreateCommand",
    "CharacterCreationError",
    "CharacterCreationResult",
    "CharacterCultivationError",
    "CharacterEquipPlan",
    "CharacterGenderPlan",
    "CharacterGrowthPlan",
    "CharacterInputError",
    "CharacterLawPlan",
    "CharacterMedicineSettingPlan",
    "CharacterNotFoundError",
    "CharacterProfile",
    "CharacterPublicProfile",
    "CharacterRecoveryPlan",
    "CharacterRetreatPlan",
    "CharacterSpiritStonePlan",
    "CharacterStateError",
    "CharacterStatus",
    "CharacterTechniqueUpgradePlan",
    "EquippedContent",
    "InventorySummary",
    "WeaponProfile",
]
