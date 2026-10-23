"""阵法炼制、待战和战斗快照的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import NamedTuple

from game.core.database import StateMutation
from game.core.innate_treasure import InnateTreasureActivation


class FormationError(ValueError):
    """阵法规则或请求无法完成。"""


class FormationUnavailableError(FormationError):
    """当前位置没有阵师或未开放指定阵法。"""


class FormationMaterialError(FormationError):
    """三相材料不足。"""


class FormationCandidate(NamedTuple):
    """一条候选项：显示名（带投入）＋ 两种命令写法各自的尾串 ＋ 一句 muted 说明。

    两种尾串是因为命令语法不同：`布阵`／`炼阵` 是「品级阵法名 + 三个投入数」，
    `演阵台` 是「阵法名 + 品级 + 三个投入数」。各命令取自己那一份，别互相猜。
    """

    label: str
    tail: str
    detail: str
    hall_tail: str = ""
    #: 条目键本身（如 05530007{兽宝=…}）——「布阵」没有投入位，靠它原样直中挑中那一件。
    key_tail: str = ""


class FormationChoiceError(FormationError):
    """阵藏里有多条同名阵法，需要玩家挑一件。

    `candidates` 是「显示名, 命令, 说明」三元组：命令层照它铺选择卡，点一下即精确选中。
    显示名里带投入，玩家才分得出同名同品级同灵宝的那几件。
    """

    def __init__(
        self, message: str, candidates: tuple[FormationCandidate, ...]
    ) -> None:
        super().__init__(message)
        self.candidates = candidates


class FormationConflictError(FormationError):
    """阵法提交时相关状态已经变化。"""


@dataclass(frozen=True)
class FormationStatus:
    initialized: bool
    formation_count: int
    master_count: int
    fixed_grade_count: int
    unlimited_grade: str


@dataclass(frozen=True)
class FormationMaster:
    master_id: str
    name: str
    location_name: str
    title: str
    platform_name: str
    speech_style: str
    speech: Mapping[str, str]
    formation_ids: tuple[str, ...]


@dataclass(frozen=True)
class FormationDefinition:
    formation_id: str
    name: str
    monitors: tuple[str, ...]
    core: str


@dataclass(frozen=True)
class FormationMaterial:
    category: str
    item_id: str
    name: str
    grade_id: str
    grade_name: str
    quantity: int


@dataclass(frozen=True)
class FormationRequirement:
    category: str
    required: int
    selected: int

    @property
    def missing(self) -> int:
        return max(0, self.required - self.selected)


@dataclass(frozen=True)
class FormationAssessment:
    formation: FormationDefinition
    grade_id: str
    grade_name: str
    materials: tuple[FormationMaterial, ...]
    requirements: tuple[FormationRequirement, ...]
    capacity: float
    impact: float
    nodes: int
    transmission: float
    can_form: bool


@dataclass(frozen=True)
class FormationPreview:
    user_id: str
    location_name: str
    master: FormationMaster
    formation: FormationDefinition
    grade_id: str
    grade_name: str
    request_text: str
    materials: tuple[FormationMaterial, ...]
    requirements: tuple[FormationRequirement, ...]
    capacity: float
    impact: float
    nodes: int
    transmission: float
    can_form: bool


@dataclass(frozen=True)
class FormationEntry:
    formation: FormationDefinition


@dataclass(frozen=True)
class FormationOverview:
    user_id: str
    location_name: str
    master: FormationMaster
    entries: tuple[FormationEntry, ...]
    page: int
    page_count: int


@dataclass(frozen=True)
class FormationResult:
    preview: FormationPreview
    reserve_key: str
    quantity_before: int
    quantity_after: int
    replayed: bool
    treasure_activation: InnateTreasureActivation | None = None


@dataclass(frozen=True)
class FormationPrepared:
    user_id: str
    reserve_key: str
    formation_id: str
    name: str
    grade_id: str
    grade_name: str
    materials: tuple[tuple[str, str], ...]
    treasure_id: str
    modifiers: tuple[tuple[str, str], ...]
    version: int
    #: 灵宝加成的可读描述（「名字 · 能力摘要」）；没有灵宝就是空串。形状由定义类型的包给。
    treasure_line: str = ""


@dataclass(frozen=True)
class FormationArmResult:
    prepared: FormationPrepared
    replayed: bool


@dataclass(frozen=True)
class FormationStageProfile:
    threshold_multiplier: float
    cycle_multiplier: float
    impact_multiplier: float


@dataclass(frozen=True)
class FormationNodeRules:
    enemy_formation_first: bool
    target_count_field: str
    target_sort: tuple[str, ...]
    impact_distribution: str
    unique_targets: bool
    minimum_targets: int


@dataclass(frozen=True)
class FormationBattleProfile:
    formation_id: str
    name: str
    grade_name: str
    position: int
    capacity: float
    impact: float
    nodes: int
    transmission: float
    stages: tuple[FormationStageProfile, ...]


@dataclass(frozen=True)
class FormationActivationPlan:
    prepared: FormationPrepared
    profile: FormationBattleProfile
    operation: StateMutation


__all__ = [
    "FormationActivationPlan",
    "FormationArmResult",
    "FormationAssessment",
    "FormationBattleProfile",
    "FormationConflictError",
    "FormationChoiceError",
    "FormationDefinition",
    "FormationEntry",
    "FormationError",
    "FormationMaster",
    "FormationMaterial",
    "FormationMaterialError",
    "FormationNodeRules",
    "FormationOverview",
    "FormationPrepared",
    "FormationPreview",
    "FormationRequirement",
    "FormationResult",
    "FormationStageProfile",
    "FormationStatus",
    "FormationUnavailableError",
]
