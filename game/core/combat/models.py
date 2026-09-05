"""战斗运行期模型。

JSON 定义规则，Python 只保存一次战斗中实际发生的状态与结算上下文。
"""

from __future__ import annotations

import copy
import random
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, Any

from game.core.formation import FormationNodeRules

if TYPE_CHECKING:
    from .engine import BattleEngine

from .contracts import BattleEvent, CombatMedicineSpec


@dataclass(frozen=True)
class CombatCatalog:
    attributes: Mapping[str, Mapping[str, Any]]
    mechanisms: Mapping[str, Mapping[str, Any]]
    mechanism_names: Mapping[str, str]
    abilities: Mapping[str, Mapping[str, Any]]
    events: Mapping[str, Mapping[str, Any]]
    resources: Mapping[str, Mapping[str, Any]]
    damage_rules: Mapping[str, Any]
    action_rules: Mapping[str, Any]
    timing: Mapping[str, Any]
    status_reactions: tuple[Mapping[str, Any], ...]
    environments: Mapping[str, Mapping[str, Any]]
    environment_rules: Mapping[str, Any]
    five_elements: Mapping[str, Any]
    formation_rules: FormationNodeRules

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> CombatCatalog:
        source = value or {}
        raw_events = source.get("事件") or {}
        if not isinstance(raw_events, Mapping):
            raise TypeError("战斗事件必须使用事件契约对象")
        events = {str(key): dict(definition) for key, definition in raw_events.items()}
        return cls(
            attributes=dict(source.get("属性") or {}),
            mechanisms=dict(source.get("机制") or {}),
            mechanism_names={
                str(key): str(name)
                for key, name in dict(source.get("机制名称") or {}).items()
            },
            abilities=dict(source.get("原子能力") or {}),
            events=events,
            resources=dict(source.get("资源") or {}),
            damage_rules=dict(source.get("伤害规则") or {}),
            action_rules=dict(source.get("行动规则") or {}),
            timing=dict(source.get("时序") or {}),
            status_reactions=tuple(copy.deepcopy(source.get("状态反应") or ())),
            environments=dict(source.get("战场环境") or {}),
            environment_rules=dict(source.get("环境规则") or {}),
            five_elements=dict(source.get("五行") or {}),
            formation_rules=source["阵法规则"],
        )

    def require_mechanism(self, key: str) -> Mapping[str, Any]:
        try:
            return self.mechanisms[str(key)]
        except KeyError as exc:
            raise ValueError(f"战斗核心未登记机制：{key}") from exc

    def require_event(self, key: str) -> Mapping[str, Any]:
        try:
            return self.events[str(key)]
        except KeyError as exc:
            raise ValueError(f"战斗核心未登记事件：{key}") from exc

    def mechanism_name(self, key: str) -> str:
        return self.mechanism_names.get(str(key), str(key))

    def parse_node(self, value: Mapping[str, Any]) -> RuleNode:
        ability = str(value.get("能力") or "")
        try:
            definition = self.abilities[ability]
        except KeyError as exc:
            raise ValueError(f"战斗核心未登记原子能力：{ability or '<空>'}") from exc
        return RuleNode(
            ability=ability,
            executor=str(definition.get("执行器") or ""),
            category=str(definition.get("类别") or ""),
            values=value,
        )

    def require_node(self, key: str) -> RuleNode:
        return self.parse_node(self.require_mechanism(key))


@dataclass(frozen=True)
class RuleNode:
    ability: str
    executor: str
    category: str
    values: Mapping[str, Any]


@dataclass
class StatusState:
    name: str
    category: str = "中性"
    remaining_turns: int = 1
    source: str = ""
    source_name: str = ""
    source_mechanism: str = ""
    build_instance: str = ""
    modifiers: dict[str, float] = dataclass_field(default_factory=dict)
    stacks: int = 1
    max_stacks: int = 1
    tags: tuple[str, ...] = ()
    duration_unit: str = "状态承受者行动"
    action_limits: tuple[str, ...] = ()
    effect_immunities: tuple[str, ...] = ()
    listeners: tuple[Mapping[str, Any], ...] = ()
    values: dict[str, Any] = dataclass_field(default_factory=dict)
    expire_with_source: bool = False

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> StatusState:
        allowed = {
            "名称", "类别", "剩余行动", "来源", "来源名称", "来源机制", "构筑实例", "属性", "层数",
            "层数上限", "标签", "持续单位", "行动限制", "效果免疫", "监听", "记录",
            "来源退场时移除", "叠加范围", "重复方式", "允许跨构筑", "是否控制", "控制基础命中率",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError("状态存在未知字段：" + "、".join(sorted(str(item) for item in unknown)))
        return cls(
            name=str(value.get("名称") or "").strip(),
            category=str(value.get("类别") or "中性").strip(),
            remaining_turns=max(0, int(value.get("剩余行动", 1) or 0)),
            source=str(value.get("来源") or "").strip(),
            source_name=str(value.get("来源名称") or "").strip(),
            source_mechanism=str(value.get("来源机制") or "").strip(),
            build_instance=str(value.get("构筑实例") or "").strip(),
            modifiers={str(k): float(v) for k, v in dict(value.get("属性") or {}).items()},
            stacks=max(1, int(value.get("层数") or 1)),
            max_stacks=max(1, int(value.get("层数上限") or 1)),
            tags=tuple(str(item) for item in value.get("标签") or ()),
            duration_unit=str(value.get("持续单位") or "状态承受者行动"),
            action_limits=tuple(str(item) for item in value.get("行动限制") or ()),
            effect_immunities=tuple(str(item) for item in value.get("效果免疫") or ()),
            listeners=tuple(copy.deepcopy(item) for item in value.get("监听") or ()),
            values=copy.deepcopy(dict(value.get("记录") or {})),
            expire_with_source=bool(value.get("来源退场时移除", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "名称": self.name,
            "类别": self.category,
            "剩余行动": self.remaining_turns,
            "来源": self.source,
            "来源名称": self.source_name,
            "来源机制": self.source_mechanism,
            "构筑实例": self.build_instance,
            "属性": dict(self.modifiers),
            "层数": self.stacks,
            "层数上限": self.max_stacks,
            "标签": list(self.tags),
            "持续单位": self.duration_unit,
            "行动限制": list(self.action_limits),
            "效果免疫": list(self.effect_immunities),
            "监听": copy.deepcopy(list(self.listeners)),
            "记录": copy.deepcopy(self.values),
            "来源退场时移除": self.expire_with_source,
        }


@dataclass
class Skill:
    key: str
    name: str
    born_order: int = 0
    release_order: int = 1
    source_id: str = ""
    source_category: str = "功法"
    build_instance: str = ""
    ability_order: int = 0
    multiplier: float = 1.0
    spirit_cost: float = 0.0
    cooldown_actions: int = 0
    effects: tuple[Mapping[str, Any], ...] = ()
    tags: tuple[str, ...] = ()
    costs: tuple[Mapping[str, Any], ...] = ()
    disabled: bool = False
    uses: int = 0
    use_limit: int = 0
    cooldown_group: str = ""
    rollback_on_failure: bool = False
    source_skill: str = ""
    temporary_changes: dict[str, Any] = dataclass_field(default_factory=dict)
    element_composition: Mapping[str, float] = dataclass_field(
        default_factory=lambda: {"无相": 100}
    )
    # 构筑词条表只随运行期技能传递，不进入公共战斗目录。
    term_table: Mapping[str, Any] = dataclass_field(default_factory=dict)

    def clone(self, *, key: str, name: str | None = None) -> Skill:
        value = copy.deepcopy(self)
        value.key = key
        value.name = name or self.name
        value.source_skill = self.key
        value.uses = 0
        return value


@dataclass
class Fighter:
    id: str
    name: str
    attributes: dict[str, float]
    health: float
    spirit: float
    shield: float = 0.0
    statuses: list[StatusState] = dataclass_field(default_factory=list)
    skills: list[Skill] = dataclass_field(default_factory=list)
    passives: list[dict[str, Any]] = dataclass_field(default_factory=list)
    cooldowns: dict[str, int] = dataclass_field(default_factory=dict)
    inventory: dict[str, int] = dataclass_field(default_factory=dict)
    inventory_owner_id: str = ""
    auto_medicine: bool = False
    medicine_threshold: float = 0.3
    consumed_items: dict[str, int] = dataclass_field(default_factory=dict)
    skill_cursor: int = 0
    current_skill: str = ""
    level: int = 1
    combatant_type: str = "修士"
    side: int = 0
    owner_id: str = ""
    controller_id: str = ""
    group_id: str = ""
    group_role: str = "主战者"
    form: str = "本相"
    forms: dict[str, Mapping[str, Any]] = dataclass_field(default_factory=dict)
    form_modifiers: dict[str, float] = dataclass_field(default_factory=dict)
    base_form_skills: list[Skill] | None = None
    tags: set[str] = dataclass_field(default_factory=set)
    tactic: list[Mapping[str, Any]] = dataclass_field(default_factory=list)
    battle_profile: dict[str, Any] = dataclass_field(default_factory=dict)
    gender: str = ""
    active: bool = True
    summoned: bool = False
    summon_template: str = ""
    can_act: bool = True
    counts_for_victory: bool = True
    five_elements: dict[str, float] = dataclass_field(default_factory=dict)
    team_synergy: dict[str, int] = dataclass_field(default_factory=dict)

    def value(self, key: str, default: float = 0.0) -> float:
        result = float(self.attributes.get(key, default))
        for status in self.statuses:
            result += float(status.modifiers.get(key, 0.0)) * max(1, status.stacks)
        return result

    @property
    def alive(self) -> bool:
        return self.active and self.health > 0

    @property
    def health_max(self) -> float:
        return max(1.0, self.value("血气上限", 1.0))

    @property
    def spirit_max(self) -> float:
        return max(0.0, self.value("精神上限", 0.0))

    @property
    def shield_max(self) -> float:
        return max(0.0, self.value("护盾上限", 0.0))


ListenerEntry = tuple[
    tuple[Any, ...],
    Fighter,
    str,
    str,
    str,
    Mapping[str, Any],
    Mapping[str, float],
    Mapping[str, Any],
]


@dataclass
class CombatObject:
    id: str
    name: str
    object_type: str
    side: int
    owner_id: str
    remaining_actions: int = 0
    health: float = 0.0
    listeners: list[Mapping[str, Any]] = dataclass_field(default_factory=list)
    values: dict[str, Any] = dataclass_field(default_factory=dict)
    tags: set[str] = dataclass_field(default_factory=set)
    active: bool = True


@dataclass
class EventFrame:
    kind: str
    source: Fighter
    target: Fighter
    facts: dict[str, Any] = dataclass_field(default_factory=dict)
    tags: set[str] = dataclass_field(default_factory=set)
    cancelled: bool = False
    transformed_kind: str = ""
    original_kind: str = ""

    def __post_init__(self) -> None:
        if not self.original_kind:
            self.original_kind = self.kind

    @property
    def amount(self) -> float:
        return float(self.facts.get("当前数值", self.facts.get("实际数值", 0.0)) or 0.0)


@dataclass
class ActionIntent:
    actor_id: str
    action: str
    target_id: str
    skill_key: str = ""
    cancelled: bool = False


@dataclass(frozen=True)
class RuntimeCombatantSnapshot:
    id: str
    name: str
    attributes: Mapping[str, float]
    level: int = 1
    combatant_type: str = "修士"
    weapon_attack: float = 0.0
    techniques: tuple[Mapping[str, Any], ...] = ()
    health: float | None = None
    spirit: float | None = None
    shield: float = 0.0
    statuses: tuple[Mapping[str, Any], ...] = ()
    cooldowns: Mapping[str, int] = dataclass_field(default_factory=dict)
    inventory: Mapping[str, int] = dataclass_field(default_factory=dict)
    inventory_owner_id: str = ""
    auto_medicine: bool = False
    medicine_threshold: float = 0.3
    skill_cursor: int = 0
    owner_id: str = ""
    controller_id: str = ""
    group_id: str = ""
    group_role: str = "主战者"
    form: str = "本相"
    forms: Mapping[str, Mapping[str, Any]] = dataclass_field(default_factory=dict)
    tags: tuple[str, ...] = ()
    tactic: tuple[Mapping[str, Any], ...] = ()
    battle_profile: Mapping[str, Any] = dataclass_field(default_factory=dict)
    gender: str = ""
    five_elements: Mapping[str, float] = dataclass_field(
        default_factory=lambda: {"木": 20, "火": 20, "土": 20, "金": 20, "水": 20}
    )


@dataclass(frozen=True)
class PreparedFieldStage:
    name: str
    threshold: float
    entry_abilities: tuple[Mapping[str, Any], ...]
    passive_abilities: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class PreparedCombatField:
    environment_id: str
    name: str
    scene: str
    origin: str
    xy: tuple[int, int] | None
    altitude: int | None
    terrain: str
    stages: tuple[PreparedFieldStage, ...]


@dataclass(frozen=True)
class PreparedFormationStage:
    threshold_multiplier: float
    cycle_multiplier: float
    impact_multiplier: float


@dataclass(frozen=True)
class PreparedFormation:
    formation_id: str
    name: str
    grade: str
    side: int
    position: int
    capacity: float
    impact: float
    nodes: int
    transmission: float
    stages: tuple[PreparedFormationStage, ...]


@dataclass
class RuntimeFormation:
    definition: PreparedFormation
    remaining_capacity: float
    next_rotation: int
    rotations: int = 0
    collapsed: bool = False

    @property
    def side(self) -> int:
        return self.definition.side

    @property
    def active(self) -> bool:
        return not self.collapsed and self.remaining_capacity > 0


@dataclass
class RuntimeCombatField:
    definition: PreparedCombatField
    source: Fighter
    health_basis: float
    accumulated_damage: float = 0.0
    stage_index: int = 0

    @property
    def stage(self) -> PreparedFieldStage:
        return self.definition.stages[self.stage_index]

    @property
    def damage_ratio(self) -> float:
        if self.health_basis <= 0:
            return 0.0
        return self.accumulated_damage / self.health_basis


@dataclass
class BattleContext:
    rng: random.Random
    left: Fighter
    right: Fighter
    medicine_definitions: dict[str, CombatMedicineSpec]
    medicine_selection_strategy: str = ""
    field: RuntimeCombatField | None = None
    formations: list[RuntimeFormation] = dataclass_field(default_factory=list)
    left_team: list[Fighter] = dataclass_field(default_factory=list)
    right_team: list[Fighter] = dataclass_field(default_factory=list)
    events: list[BattleEvent] = dataclass_field(default_factory=list)
    action_number: int = 0
    engine: BattleEngine | None = None
    trigger_counts: dict[tuple[str, str], int] = dataclass_field(default_factory=dict)
    battle_trigger_counts: dict[tuple[str, str], int] = dataclass_field(default_factory=dict)
    event_depth: int = 0
    mechanism_depth: int = 0
    triggered_skill_depth: int = 0
    action_progress: dict[str, float] = dataclass_field(default_factory=dict)
    mechanism_counters: dict[tuple[str, str, str], float] = dataclass_field(default_factory=dict)
    current_mechanism: str = ""
    current_build_instance: str = ""
    current_element_composition: dict[str, float] = dataclass_field(
        default_factory=lambda: {"无相": 100}
    )
    current_term_table: Mapping[str, Any] = dataclass_field(default_factory=dict)
    trigger_stack: set[tuple[str, str]] = dataclass_field(default_factory=set)
    event_stack: list[EventFrame] = dataclass_field(default_factory=list)
    records: dict[tuple[str, str], list[Any]] = dataclass_field(default_factory=dict)
    relations: list[dict[str, Any]] = dataclass_field(default_factory=list)
    combat_objects: dict[str, CombatObject] = dataclass_field(default_factory=dict)
    battle_rules: list[dict[str, Any]] = dataclass_field(default_factory=list)
    saved_results: dict[str, Any] = dataclass_field(default_factory=dict)
    last_result: dict[str, Any] = dataclass_field(default_factory=dict)
    effect_history: list[dict[str, Any]] = dataclass_field(default_factory=list)
    action_intent: ActionIntent | None = None
    judgement_overrides: dict[str, list[dict[str, Any]]] = dataclass_field(default_factory=dict)
    summon_serial: int = 0
    # Runtime indexes are derived state. They are rebuilt when a transaction
    # restores team membership or a summon enters the battle.
    fighters_by_id: dict[str, Fighter] = dataclass_field(default_factory=dict, init=False)
    fighter_order: dict[str, int] = dataclass_field(default_factory=dict, init=False)
    _fighters_cache: tuple[Fighter, ...] = dataclass_field(default_factory=tuple, init=False, repr=False)
    listener_index: dict[str, tuple[ListenerEntry, ...]] = dataclass_field(
        default_factory=dict, init=False, repr=False
    )
    listener_index_dirty: bool = dataclass_field(default=True, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.left_team:
            self.left_team = [self.left]
        if not self.right_team:
            self.right_team = [self.right]
        for fighter in self.left_team:
            fighter.side = 0
        for fighter in self.right_team:
            fighter.side = 1
        self.rebuild_indexes()

    def rebuild_indexes(self) -> None:
        """Rebuild derived indexes after structural state restoration."""

        self._fighters_cache = (*self.left_team, *self.right_team)
        self.fighters_by_id = {fighter.id: fighter for fighter in self._fighters_cache}
        self.fighter_order = {
            fighter.id: index for index, fighter in enumerate(self._fighters_cache)
        }
        self.listener_index.clear()
        self.listener_index_dirty = True

    def mark_listener_index_dirty(self) -> None:
        self.listener_index_dirty = True

    @property
    def fighters(self) -> tuple[Fighter, ...]:
        return self._fighters_cache

    @property
    def both_sides_alive(self) -> bool:
        return any(value.alive and value.counts_for_victory for value in self.left_team) and any(value.alive and value.counts_for_victory for value in self.right_team)

    def side_index(self, fighter: Fighter) -> int:
        if fighter not in self.fighters:
            raise ValueError("参战者不属于当前战斗")
        return fighter.side

    def allies_of(self, fighter: Fighter, *, alive: bool | None = True) -> list[Fighter]:
        values = self.left_team if fighter.side == 0 else self.right_team
        return [value for value in values if alive is None or value.alive is alive]

    def enemies_of(self, fighter: Fighter, *, alive: bool | None = True) -> list[Fighter]:
        values = self.right_team if fighter.side == 0 else self.left_team
        return [value for value in values if alive is None or value.alive is alive]

    def opponent_of(self, fighter: Fighter) -> Fighter:
        candidates = self.enemies_of(fighter)
        if not candidates:
            raise ValueError("对方阵营已无存活参战者")
        return candidates[0] if len(candidates) == 1 else self.rng.choice(candidates)

    def fighter_by_id(self, fighter_id: str) -> Fighter | None:
        return self.fighters_by_id.get(str(fighter_id))

    def add_fighter(self, fighter: Fighter) -> None:
        target = self.left_team if fighter.side == 0 else self.right_team
        if self.fighter_by_id(fighter.id) is not None:
            raise ValueError(f"战斗对象 ID 重复：{fighter.id}")
        target.append(fighter)
        fighter.side = 0 if target is self.left_team else 1
        self.action_progress[fighter.id] = 0.0
        self.rebuild_indexes()

    def event(
        self,
        kind: str,
        source: Fighter,
        target: Fighter,
        text: str,
        amount: float = 0.0,
        *,
        values: Mapping[str, Any] | None = None,
        tags: tuple[str, ...] = (),
        mechanism: str = "",
        dispatch: bool = True,
    ) -> EventFrame | None:
        event_values = dict(values or {})
        event_values.setdefault("当前数值", float(amount))
        frame = None
        if dispatch and self.engine is not None:
            frame = self.engine._dispatch_event(
                self,
                kind=kind,
                source=source,
                target=target,
                amount=float(amount),
                values=event_values,
                tags=tuple(tags),
                record=False,
            )
            event_values = dict(frame.facts)
            target = frame.target
            kind = frame.transformed_kind or frame.kind
        self.events.append(
            BattleEvent(
                self.action_number,
                kind,
                source.name,
                target.name,
                text,
                round(float(event_values.get("实际数值", event_values.get("当前数值", amount)) or 0), 3),
                event_values,
                tuple(tags),
                mechanism,
                source.id,
                target.id,
            )
        )
        return frame
