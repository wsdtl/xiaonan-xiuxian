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

#: 不可变标量。容器里只有这些值时，重建容器与深拷贝**语义完全一致**（标量不可变，
#: 不存在别名风险），所以能省掉整棵树的递归。见 `copy_value`。
ATOMIC_TYPES = frozenset({str, int, float, bool, bytes, type(None)})


def copy_value(value: Any) -> Any:
    """`copy.deepcopy` 的快路径：全原子容器直接重建，其余原样退回深拷贝。

    战斗中绝大多数的拷贝对象是「键是字符串、值是标量」的字典（事件事实、状态记录），
    深拷贝这类字典要走上百次 `_deepcopy_*` 调用，而结果与 `dict(value)` 一模一样。
    只要出现一个容器值就退回深拷贝，所以调用方拿到的隔离强度不变。
    """

    kind = type(value)
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str or type(item) not in ATOMIC_TYPES:
                return copy.deepcopy(value)
        return dict(value)
    if kind is list:
        for item in value:
            if type(item) not in ATOMIC_TYPES:
                return copy.deepcopy(value)
        return list(value)
    if kind is tuple:
        for item in value:
            if type(item) not in ATOMIC_TYPES:
                return copy.deepcopy(value)
        # 元组不可变：深拷贝对全原子元组本来也返回同一个对象。
        return value
    return copy.deepcopy(value)


@dataclass(frozen=True)
class CombatCatalog:
    attributes: Mapping[str, Mapping[str, Any]]
    abilities: Mapping[str, Mapping[str, Any]]
    events: Mapping[str, Mapping[str, Any]]
    resources: Mapping[str, Any]
    damage_rules: Mapping[str, Any]
    action_rules: Mapping[str, Any]
    timing: Mapping[str, Any]
    status_reactions: tuple[Mapping[str, Any], ...]
    environments: Mapping[str, Mapping[str, Any]]
    environment_rules: Mapping[str, Any]
    five_elements: Mapping[str, Any]
    formation_rules: FormationNodeRules
    #: 地形战斗节奏（`data/战斗/规则/地形.json`）：地形 → 输出倍率百分比；无名之地按进度加。
    terrain_pace: Mapping[str, Any] = dataclass_field(default_factory=dict)
    #: 规则层登记表（`data/战斗/定义/规则层.json`）：单位级规则在装配期按它解析。
    rule_layer: Mapping[str, Mapping[str, Any]] = dataclass_field(default_factory=dict)
    #: 构筑模板库。放在最后并给默认值，让既有构造点不必都改。
    #: 模板引用在**装载期**已展开（见 `service.expand_build_section`），所以引擎
    #: 解析时不需要再用它；保留字段是为了让基线与诊断能看到当前模板库。
    templates: Mapping[str, Mapping[str, Any]] = dataclass_field(default_factory=dict)
    #: 节点解析缓存：`id(节点) -> RuleNode`（见 `parse_node`）。装配期节点不换，按身份缓存安全。
    _node_cache: dict[int, RuleNode] = dataclass_field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any] | None,
        templates: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> CombatCatalog:
        source = value or {}
        raw_events = source.get("事件") or {}
        if not isinstance(raw_events, Mapping):
            raise TypeError("战斗事件必须使用事件契约对象")
        events = {str(key): dict(definition) for key, definition in raw_events.items()}
        return cls(
            attributes=dict(source.get("属性") or {}),
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
            rule_layer=dict(source.get("规则层") or {}),
            terrain_pace=dict(source.get("地形节奏") or {}),
            templates=dict(templates or {}),
        )

    def require_event(self, key: str) -> Mapping[str, Any]:
        try:
            return self.events[str(key)]
        except KeyError as exc:
            raise ValueError(f"战斗核心未登记事件：{key}") from exc

    def terrain_percent(self, terrain: str) -> float | None:
        """这场仗所在**地形**的战斗节奏（百分比）；没登记过这条地形就返回空。"""

        name = str(terrain or "").strip()
        if not name:
            return None
        for row in self.terrain_pace.get("地形") or ():
            if str(row.get("地形") or "") == name:
                return float(row.get("输出倍率") or 100)
        return None

    def formless_percent(self, level: int) -> float:
        """**无名之地**（没特殊地势 / 场地没登记）的战斗节奏：随进度加。

        倍率 = `基础倍率` + 等级 × `每级加成`——等级越高出手越决，仗打得越快。
        """

        rule = self.terrain_pace.get("无相地势") or {}
        base = float(rule.get("基础倍率") or 100)
        per_level = float(rule.get("每级加成") or 0)
        return base + max(0, int(level)) * per_level

    def parse_node(self, value: Mapping[str, Any]) -> RuleNode:
        """把一个能力节点解析成 `RuleNode`（按对象身份记忆化）。

        同一个节点在一场仗里会被反复执行（监听一次触发一次），而解析只是查一次登记表；
        节点对象来自装配期的深拷贝、一场仗里不换，所以按 `id` 缓存是安全的——判据里
        `parse_node` 的调用量是十几万次，这一层缓存省掉其中绝大部分。
        """

        cached = self._node_cache.get(id(value))
        if cached is not None and cached.values is value:
            return cached
        ability = str(value.get("能力") or "")
        try:
            definition = self.abilities[ability]
        except KeyError as exc:
            raise ValueError(f"战斗核心未登记原子能力：{ability or '<空>'}") from exc
        node = RuleNode(
            ability=ability,
            executor=str(definition.get("执行器") or ""),
            category=str(definition.get("类别") or ""),
            values=value,
        )
        self._node_cache[id(value)] = node
        return node


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
    source_ability: str = ""
    build_instance: str = ""
    modifiers: dict[str, float] = dataclass_field(default_factory=dict)
    stacks: int = 1
    max_stacks: int = 1
    tags: tuple[str, ...] = ()
    duration_unit: str = "状态承受者行动"
    action_limits: tuple[str, ...] = ()
    listeners: tuple[Mapping[str, Any], ...] = ()
    #: 状态自带的**单位级规则**（`规则层.json` 的登记项）：状态在就生效、状态一走就失效。
    #: 规则本身不走效果管线，所以效果里的「取消 / 转化 / 无效」碰不到它。
    rules: dict[str, dict[str, Any]] = dataclass_field(default_factory=dict)
    values: dict[str, Any] = dataclass_field(default_factory=dict)
    expire_with_source: bool = False

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> StatusState:
        allowed = {
            "名称", "类别", "剩余行动", "来源", "来源名称", "来源能力", "构筑实例", "属性", "层数",
            "层数上限", "标签", "持续单位", "行动限制", "监听", "规则", "记录",
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
            source_ability=str(value.get("来源能力") or "").strip(),
            build_instance=str(value.get("构筑实例") or "").strip(),
            modifiers={str(k): float(v) for k, v in dict(value.get("属性") or {}).items()},
            stacks=max(1, int(value.get("层数") or 1)),
            max_stacks=max(1, int(value.get("层数上限") or 1)),
            tags=tuple(str(item) for item in value.get("标签") or ()),
            duration_unit=str(value.get("持续单位") or "状态承受者行动"),
            action_limits=tuple(str(item) for item in value.get("行动限制") or ()),
            listeners=tuple(copy_value(item) for item in value.get("监听") or ()),
            values=copy_value(dict(value.get("记录") or {})),
            expire_with_source=bool(value.get("来源退场时移除", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
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
            "监听": copy_value(list(self.listeners)),
            "记录": copy_value(self.values),
            "来源退场时移除": self.expire_with_source,
        }
        # 只有真带规则的状态才多这个键：这条 `to_dict` 会进事件事实（`复制状态` 把状态定义
        # 整个记进去），多一个恒为空数组的键会让所有战报的摘要漂掉。
        if self.rules:
            result["规则"] = [
                {"名称": name, **dict(rule.get("参数") or {})}
                for name, rule in self.rules.items()
            ]
        return result


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
    #: 这一行自己的规则（行级）：`规则名 -> 展开后的规则`，见 `data/战斗/定义/规则层.json`。
    rules: dict[str, dict[str, Any]] = dataclass_field(default_factory=dict)
    uses: int = 0
    use_limit: int = 0
    cooldown_group: str = ""
    rollback_on_failure: bool = False
    source_skill: str = ""
    temporary_changes: dict[str, Any] = dataclass_field(default_factory=dict)
    element_composition: Mapping[str, float] = dataclass_field(
        default_factory=lambda: {"无相": 100}
    )

    def clone(self, *, key: str, name: str | None = None) -> Skill:
        value = copy_skill(self)
        value.key = key
        value.name = name or self.name
        value.source_skill = self.key
        value.uses = 0
        return value


def copy_skill(skill: Skill) -> Skill:
    """技能对象的结构拷贝。

    `copy.deepcopy` 会把**整棵效果定义**再拷一遍，但效果定义是只读的卡面数据：
    运行时改写技能走的是「整个字段换掉」（见 `_ability_modify_skill`），从不就地改
    元组里的字典。所以这里只复制真会被就地改的三张字典（行级规则 / 临时变化 /
    属性构成），标量与元组共享。实测这样与深拷贝逐事件一致，省掉战斗里最贵的一段拷贝。
    """

    cloned = copy.copy(skill)
    cloned.rules = copy.deepcopy(skill.rules)
    cloned.temporary_changes = dict(skill.temporary_changes)
    cloned.element_composition = dict(skill.element_composition)
    return cloned


def copy_skills(skills: list[Skill]) -> list[Skill]:
    """技能列表的结构拷贝：列表本身新建，每个技能见 `copy_skill`。"""

    return [copy_skill(skill) for skill in skills]


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
    #: 规则层的单位级规则：`规则名 -> 参数`（见 `data/战斗/定义/规则层.json`）。
    rules: dict[str, dict[str, Any]] = dataclass_field(default_factory=dict)
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
    #: 按拦截点分好的规则表 + 它对应的版本号（见 `mechanics._container_rules`）。
    rules_cache: dict = dataclass_field(default_factory=dict, init=False, repr=False)
    rules_cache_version: int = dataclass_field(default=-1, init=False, repr=False)

    def value(self, key: str, default: float = 0.0) -> float:
        # 这一条是全战斗最热的读法（每次算血气上限都走它）：循环里不放 `max()` 与
        # `float()`，没有这个键的状态直接跳过——语义与原来逐字一致。
        result = self.attributes.get(key, default)
        for status in self.statuses:
            modifier = status.modifiers.get(key)
            if modifier:
                stacks = status.stacks
                result += modifier * (stacks if stacks > 1 else 1)
        return float(result)

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


def attribute_ratio(
    fighter: Fighter,
    attribute: str,
    definitions: Mapping[str, Mapping[str, Any]] | None = None,
    default: float | None = None,
) -> float:
    """读一个百分比属性的**比值**：`100` → `1.0`。

    基准就是 `属性.json` 里这个属性自己的 `默认值`——那才是「不增不减」的值，
    `口径` 说明它怎么被用：

    | 口径 | 基准 | 读法 |
    | --- | --- | --- |
    | 加成 | 100 | `×比值`（伤害/治疗/护盾/受疗/受盾/普攻威力/技能威力/治疗效果/护盾强度） |
    | 倍率 | 自身 | `×比值`（暴击伤害 150 = ×1.5、连击伤害 100 = ×1.0） |
    | 概率 | 0 | 百分点相抵（命中率是 100 = 必中，所以它自己那条写 100） |
    | 减免 | 0 | `- 比值`（伤害减免、格挡减伤、韧性、冷却缩减、精神消耗修正） |
    | 比率 | 0 | 直接当比率（比例穿透） |

    所以调用点**不该**再自己写 `1 + …` / `1 - …`：那是把基准又抄了一遍。
    只有「基准不是属性自己的默认值」时才传 `default`（如今只剩命中率要传伤害规则里的
    基础命中率）。
    """

    definition = dict(dict(definitions or {}).get(attribute) or {})
    baseline = float(definition.get("默认值", 0.0))
    if default is not None:
        baseline = float(default) * 100.0
    if attribute not in fighter.attributes and not any(
        attribute in status.modifiers for status in fighter.statuses
    ):
        return baseline / 100.0
    return fighter.value(attribute, baseline) / 100.0


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
    #: 参战者固有规则（锁定技）：与卡面同一张登记表，装配期并进参战者的规则表。
    inherent_rules: tuple[Mapping[str, Any], ...] = ()
    #: 计不计胜负（讨伐属从不计）。
    counts_for_victory: bool = True
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
    #: 键是（修士 id, 词条, 监听声明）；键长不固定，所以用变长元组。
    #: 追加攻击也往这里记账，它用的是（来源 id, "追加攻击"）。
    trigger_counts: dict[tuple[str, ...], int] = dataclass_field(default_factory=dict)
    battle_trigger_counts: dict[tuple[str, ...], int] = dataclass_field(default_factory=dict)
    event_depth: int = 0
    ability_depth: int = 0
    triggered_skill_depth: int = 0
    action_progress: dict[str, float] = dataclass_field(default_factory=dict)
    ability_counters: dict[tuple[str, str, str], float] = dataclass_field(default_factory=dict)
    current_ability: str = ""
    current_build_instance: str = ""
    current_element_composition: dict[str, float] = dataclass_field(
        default_factory=lambda: {"无相": 100}
    )
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
    #: 监听分桶：`事件 → (观察角色, 阵营关系) → 持有者 → [(位次, 监听条目)]`。
    #: 派发时按「阵营关系」把候选收到当事人身上，再按位次合并——顺序与 `listener_index` 逐条一致。
    listener_buckets: dict = dataclass_field(default_factory=dict, init=False, repr=False)
    listener_index_dirty: bool = dataclass_field(default=True, init=False, repr=False)
    #: 状态进出（以及事务回滚）时 +1：`_container_rules` 的规则表缓存按它失效。
    status_rules_version: int = dataclass_field(default=0, init=False, repr=False)

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
        self.listener_buckets.clear()
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
        ability: str = "",
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
                ability,
                source.id,
                target.id,
            )
        )
        return frame
