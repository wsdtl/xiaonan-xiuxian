"""战斗核心微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

BUILD_SECTIONS = frozenset({"功法", "真意", "气机", "器律"})


@dataclass(frozen=True)
class CombatStatus:
    initialized: bool
    build_count: int
    ability_count: int
    event_count: int
    environment_count: int
    formation_count: int = 0


@dataclass(frozen=True)
class CombatFieldSpec:
    """由战场服务准备、由战斗核心执行的环境引用。"""

    environment_id: str
    scene: str
    origin: str
    xy: tuple[int, int] | None = None
    altitude: int | None = None
    terrain: str = ""


@dataclass(frozen=True)
class CombatFormationSpec:
    """战场级阵法引用；阵法不占角色修行槽位。"""

    formation_id: str
    grade: str = "黄"
    position: int = 0
    materials: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class CombatMedicineSpec:
    """调用方提交的战斗恢复丹快照，不依赖物品业务对象。"""

    stack_key: str
    medicine_id: str
    grade_id: str
    resource: str
    recovery_percent: float
    grade_order: int = 0


@dataclass(frozen=True)
class CombatBuildRef:
    section: str
    content_id: str
    instance_id: str = ""
    born_order: int = 0
    power_multiplier: float = 1.0


@dataclass(frozen=True)
class CombatGroupSpec:
    """一次战斗中的编组边界；成员身份仍由 CombatantSpec 提供。"""

    group_id: str
    member_ids: tuple[str, ...]
    primary_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        members = tuple(str(value).strip() for value in self.member_ids)
        primaries = tuple(str(value).strip() for value in self.primary_ids)
        if not str(self.group_id).strip() or not members or any(not value for value in members):
            raise ValueError("编组必须有非空编号和成员")
        if len(set(members)) != len(members):
            raise ValueError("编组成员编号不能重复")
        if not primaries or any(value not in members for value in primaries):
            raise ValueError("编组主战者必须属于本编组")


@dataclass(frozen=True)
class CombatStatusSpec:
    """由其他核心服务准备、由战斗核心解析监听节点的战前状态。"""

    name: str
    category: str
    remaining_actions: int
    duration_unit: str
    modifiers: tuple[tuple[str, float], ...] = ()
    tags: tuple[str, ...] = ()
    listeners: tuple[Mapping[str, Any], ...] = ()
    source: str = ""
    source_name: str = ""
    metadata: tuple[tuple[str, str | int | float], ...] = ()
    stacks: int = 1
    maximum_stacks: int = 1
    action_limits: tuple[str, ...] = ()
    build_instance: str = ""


@dataclass(frozen=True)
class CombatantSpec:
    id: str
    name: str
    attributes: Mapping[str, float]
    level: int = 1
    combatant_type: str = "修士"
    weapon_attack: float = 0.0
    build: tuple[CombatBuildRef, ...] = ()
    health: float | None = None
    spirit: float | None = None
    shield: float = 0.0
    statuses: tuple[Mapping[str, Any], ...] = ()
    prepared_statuses: tuple[CombatStatusSpec, ...] = ()
    cooldowns: Mapping[str, int] = field(default_factory=dict)
    inventory: Mapping[str, int] = field(default_factory=dict)
    inventory_owner_id: str = ""
    auto_medicine: bool = False
    medicine_threshold: float = 0.3
    skill_cursor: int = 0
    owner_id: str = ""
    controller_id: str = ""
    group_id: str = ""
    group_role: str = "主战者"
    form: str = "本相"
    forms: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    tactic: tuple[Mapping[str, Any], ...] = ()
    battle_profile: Mapping[str, Any] = field(default_factory=dict)
    gender: str = ""
    five_elements: Mapping[str, float] = field(
        default_factory=lambda: {"木": 20, "火": 20, "土": 20, "金": 20, "水": 20}
    )
    #: **参战者固有规则**（锁定技）：`[{"名称": …, 参数…}]`，与卡面 `规则文本` 同一形状。
    #: 它不属于任何一张卡——种族、来历这类「这个人天生如此」的东西从这条口子进来。
    inherent_rules: tuple[Mapping[str, Any], ...] = ()
    #: **计不计胜负**：讨伐的属从不算（斩首即胜，也把「打赢了还在磨」的时间砍掉）。默认计。
    counts_for_victory: bool = True


@dataclass(frozen=True)
class CombatantReportSpec:
    id: str
    title: str = ""
    color: str = ""
    moves: tuple[str, ...] = ()
    abilities: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CombatReportSpec:
    participants: tuple[CombatantReportSpec, ...] = ()
    scene: str = "青岚山演武台"
    generated_at: str | None = None
    include_presentation: bool = False


@dataclass(frozen=True)
class CombatRequest:
    left_team: tuple[CombatantSpec, ...]
    right_team: tuple[CombatantSpec, ...]
    seed: int
    action_limit: int
    medicine_definitions: tuple[CombatMedicineSpec, ...] = ()
    medicine_selection_strategy: str = ""
    report: CombatReportSpec | None = None
    field: CombatFieldSpec | None = None
    left_formation: CombatFormationSpec | None = None
    right_formation: CombatFormationSpec | None = None
    left_groups: tuple[CombatGroupSpec, ...] = ()
    right_groups: tuple[CombatGroupSpec, ...] = ()


@dataclass(frozen=True)
class CombatFieldResult:
    environment_id: str
    name: str
    scene: str
    origin: str
    xy: tuple[int, int] | None
    altitude: int | None
    terrain: str
    stage_index: int
    stage_name: str
    accumulated_damage: float
    health_basis: float

    @property
    def damage_ratio(self) -> float:
        if self.health_basis <= 0:
            return 0.0
        return self.accumulated_damage / self.health_basis


@dataclass(frozen=True)
class CombatFormationResult:
    formation_id: str
    name: str
    grade: str
    side: int
    position: int
    capacity: float
    remaining_capacity: float
    impact: float
    nodes: int
    rotations: int
    collapsed: bool


@dataclass(frozen=True)
class StatusResult:
    name: str
    category: str
    remaining_turns: int
    source: str
    source_name: str
    source_ability: str
    build_instance: str
    modifiers: Mapping[str, float]
    stacks: int
    max_stacks: int
    tags: tuple[str, ...]
    duration_unit: str
    action_limits: tuple[str, ...]
    listeners: tuple[Mapping[str, Any], ...]
    values: Mapping[str, Any]
    expire_with_source: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "名称": self.name,
            "类别": self.category,
            "剩余行动": self.remaining_turns,
            "来源": self.source,
            "来源名称": self.source_name,
            "来源能力": self.source_ability,
            "构筑实例": self.build_instance,
            "属性": dict(self.modifiers),
            "层数": self.stacks,
            "层数上限": self.max_stacks,
            "标签": list(self.tags),
            "持续单位": self.duration_unit,
            "行动限制": list(self.action_limits),
            "监听": [dict(value) for value in self.listeners],
            "记录": dict(self.values),
            "来源退场时移除": self.expire_with_source,
        }


@dataclass(frozen=True, slots=True)
class BattleEvent:
    turn: int
    kind: str
    source: str
    target: str
    text: str
    amount: float = 0.0
    values: Mapping[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    ability: str = ""
    source_id: str = ""
    target_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "kind": self.kind,
            "source": self.source,
            "target": self.target,
            "text": self.text,
            "amount": self.amount,
            "values": dict(self.values),
            "tags": list(self.tags),
            "ability": self.ability,
            "source_id": self.source_id,
            "target_id": self.target_id,
        }


@dataclass(frozen=True)
class CombatantResult:
    id: str
    name: str
    attributes: Mapping[str, float]
    level: int
    combatant_type: str
    health: float
    spirit: float
    shield: float
    statuses: tuple[StatusResult, ...]
    cooldowns: Mapping[str, int]
    inventory: Mapping[str, int]
    consumed_items: Mapping[str, int]
    inventory_owner_id: str
    skill_cursor: int
    form: str = "本相"
    owner_id: str = ""
    controller_id: str = ""
    group_id: str = ""
    group_role: str = "主战者"
    counts_for_victory: bool = True
    five_elements: Mapping[str, float] = field(default_factory=dict)

    @property
    def alive(self) -> bool:
        return self.health > 0


@dataclass(frozen=True)
class CombatResult:
    left: CombatantResult
    right: CombatantResult
    actions: int
    events: tuple[BattleEvent, ...]
    trigger_activations: int = 0
    left_team: tuple[CombatantResult, ...] = ()
    right_team: tuple[CombatantResult, ...] = ()
    report: Mapping[str, Any] | None = None
    presentation: tuple[Mapping[str, Any], Mapping[str, Any]] | None = None
    field: CombatFieldResult | None = None
    formations: tuple[CombatFormationResult, ...] = ()
    total_event_count: int = 0

    @property
    def left_results(self) -> tuple[CombatantResult, ...]:
        if self.left_team or self.right_team:
            return self.left_team
        return (self.left,)

    @property
    def right_results(self) -> tuple[CombatantResult, ...]:
        if self.left_team or self.right_team:
            return self.right_team
        return (self.right,)

    @property
    def winner_side(self) -> str | None:
        left_alive = any(
            result.alive and result.counts_for_victory for result in self.left_results
        )
        right_alive = any(
            result.alive and result.counts_for_victory for result in self.right_results
        )
        if left_alive == right_alive:
            return None
        return "left" if left_alive else "right"

    @property
    def winner_id(self) -> str | None:
        winner_side = self.winner_side
        if winner_side is None:
            return None
        values = self.left_results if winner_side == "left" else self.right_results
        return next(
            (value.id for value in values if value.alive and value.counts_for_victory),
            None,
        )

    @property
    def draw(self) -> bool:
        return self.winner_id is None


__all__ = [
    "BUILD_SECTIONS",
    "BattleEvent",
    "CombatBuildRef",
    "CombatFieldResult",
    "CombatFieldSpec",
    "CombatFormationResult",
    "CombatFormationSpec",
    "CombatMedicineSpec",
    "CombatReportSpec",
    "CombatRequest",
    "CombatResult",
    "CombatStatus",
    "CombatStatusSpec",
    "CombatantReportSpec",
    "CombatantResult",
    "CombatantSpec",
    "StatusResult",
]
