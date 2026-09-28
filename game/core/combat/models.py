"""战斗运行期模型。

JSON 定义规则，Python 只保存一次战斗中实际发生的状态与结算上下文。
"""

from __future__ import annotations

import copy
import random
import weakref
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field as dataclass_field
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


def copy_definition(value: Any) -> Any:
    """卡面定义（JSON 树）的深拷贝快路径：递归重建容器，标量原样带走。

    装配一条技能时要给**每一位参战者**各留一份定义，否则两个人共用同一棵定义树。
    这份定义整棵只由 `dict` / `list` / `tuple` / 标量构成——装配期实测 10,323 棵、
    174,803 个节点里只有这六种类型，**零别名、零环**——所以递归重建的结果与
    `copy.deepcopy` 逐值相等。一轮讨伐的装配期要给这 10,323 棵各拷一份：真 `deepcopy`
    花 124.9 ms（占那趟整条命令的 11.4%），本函数只要 38.8 ms。

    三处与深拷贝的差异，都按「不冒险」处理：

    * 键也过一遍本函数：`deepcopy` 连键一起拷，键同样是字符串或全原子元组，
      过一遍的结果与它逐字相同；
    * `tuple` 沿用 `copy.deepcopy` 的判据——重建后每一项都还是原对象就返回原元组
      （元组不可变，深拷贝本来也这么省）；
    * 六类之外的任何容器或对象（集合、自定义类型）**原样退回** `copy.deepcopy`，
      调用方拿到的隔离强度不变。真出了环，递归会当场 `RecursionError` 炸出来，
      不会静默串味。
    """

    kind = type(value)
    if kind is dict:
        return {
            (key if type(key) in ATOMIC_TYPES else copy_definition(key)):
            (item if type(item) in ATOMIC_TYPES else copy_definition(item))
            for key, item in value.items()
        }
    if kind is list:
        return [item if type(item) in ATOMIC_TYPES else copy_definition(item) for item in value]
    if kind is tuple:
        rebuilt = [item if type(item) in ATOMIC_TYPES else copy_definition(item) for item in value]
        for original, copied in zip(value, rebuilt):
            if original is not copied:
                return tuple(rebuilt)
        return value
    if kind in ATOMIC_TYPES:
        return value
    return copy.deepcopy(value)


def compile_definition_copy(value: Any) -> Callable[[], object]:
    """冻结 JSON 定义的复制计划；每次只重建可变容器。"""
    if type(value) is dict and all(type(key) is str for key in value):
        nested = [(key, compile_definition_copy(item)) for key, item in value.items() if type(item) not in ATOMIC_TYPES]
        base = dict(value)
        if not nested:
            return base.copy
        def clone_dict() -> object:
            result = base.copy()
            for key, clone in nested:
                result[key] = clone()
            return result
        return clone_dict
    if type(value) in (list, tuple):
        if all(type(item) in ATOMIC_TYPES for item in value):
            return value.copy if type(value) is list else lambda: value
        children = tuple(compile_definition_copy(item) for item in value)
        if type(value) is list:
            return lambda: [clone() for clone in children]
        def clone_tuple() -> object:
            result = tuple(clone() for clone in children)
            return value if all(a is b for a, b in zip(result, value)) else result
        return clone_tuple
    if type(value) in ATOMIC_TYPES:
        return lambda: value
    return lambda: copy.deepcopy(value)


def same_definition(left: object, right: object) -> bool:
    """缓存命中要保留类型：1、1.0 和 True 的普通相等不足以证明定义相同。"""
    if left is right:
        return True
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(same_definition(value, right[key]) for key, value in left.items())
    if type(left) in (list, tuple):
        return len(left) == len(right) and all(same_definition(a, b) for a, b in zip(left, right))
    return type(left) in ATOMIC_TYPES and left == right


def record_values(recorded: frozenset[str] | None, facts: Mapping[str, Any]) -> dict[str, Any]:
    """按登记表筛出**要进日志**的事实，再按需深拷（见 `copy_value`）。

    日志只记重要的动作与数据：名单在 `展示/战报.json` 的 `标准化.记录事实`，由战斗核心
    在启动时接线（`BattleEngine.recorded_facts`）。不在名单上的键（引擎记账、掷点过程、
    伤害链的中间值）**在记录这一刻就丢掉**——它们既不进事件、也不进战报与落库记录。
    筛选发生在拷贝之前，所以顺带省掉拷贝。名单为 `None` 时不筛（没接线时照旧全记）。
    """

    if recorded is None:
        return copy_value(facts)
    kept = {key: value for key, value in facts.items() if key in recorded}
    # kept 已经是新字典，标量事实不必再分配一次；嵌套值仍整体深拷，
    # 保留别名与环的隔离语义。
    for key, value in kept.items():
        if type(key) is not str or type(value) not in ATOMIC_TYPES:
            return copy.deepcopy(kept)
    return kept


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
        # 目录比单场战斗长寿；节点来自每场装配，不能永久强引用历次所有卡面。
        # 战斗上下文已有自己的执行缓存，这里只保留有界的解析缓存。
        if len(self._node_cache) >= 8192:
            self._node_cache.clear()
        self._node_cache[id(value)] = node
        return node


@dataclass(frozen=True)
class RuleNode:
    ability: str
    executor: str
    category: str
    values: Mapping[str, Any]


def _shallow_clone(value: Any) -> Any:
    """`copy.copy` 的快路径：新建同类型实例，再把 `__dict__` 逐键搬过去。

    与 `copy.copy` 的通用路（`__reduce_ex__` → `copyreg.__newobj__` → `_reconstruct`）**逐键等价**：
    同样是「新对象 + 原样搬同一批字段对象」，区别只是不走那 5~6 层分派。战斗里状态与技能在
    回滚的**取快照与还原两侧**逐对象浅拷，实测同一批 52,066 个对象上 2111.9 → 810.8 ns（2.6×），
    逐键比对（连字段值的对象身份一起比）**差异 0**。

    作为 `__copy__` 直接挂在类上（`__copy__ = _shallow_clone`）：`copy.copy` 取到的是函数本身，
    `copier(x)` 一次调用就到位，不再多绕一层方法。
    """

    clone = value.__class__.__new__(value.__class__)
    clone.__dict__.update(value.__dict__)
    return clone


class ModifierMap(dict):
    """属性修正表；公开的字典写法仍可用，写入自动作废订阅者索引。"""

    def __init__(self, values: Mapping[str, Any] | None=()) -> None:
        super().__init__(values)
        self.subscribers = {}

    def invalidate(self) -> None:
        for reference in tuple(self.subscribers.values()):
            collection = reference()
            if collection is not None:
                collection.modifier_index = None

    def __setitem__(self, key: str, value: Any) -> None:
        self.invalidate()
        super().__setitem__(key, value)

    def __delitem__(self, key: str) -> None:
        self.invalidate()
        super().__delitem__(key)

    def clear(self) -> None:
        self.invalidate()
        super().clear()

    def update(self, *args: object, **kwargs: object) -> None:
        self.invalidate()
        super().update(*args, **kwargs)

    def pop(self, *args: object) -> object:
        self.invalidate()
        return super().pop(*args)

    def popitem(self) -> tuple[object, object]:
        self.invalidate()
        return super().popitem()

    def setdefault(self, key: str, default: Any=None) -> object:
        self.invalidate()
        return super().setdefault(key, default)

    def __ior__(self, value: Any) -> ModifierMap:
        self.update(value)
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> ModifierMap:
        result = ModifierMap()
        memo[id(self)] = result
        result.update(copy.deepcopy(dict(self), memo))
        return result


class StatusList(list):
    """状态列表的属性倒排索引，保留顺序及列表增删接口。"""

    def __init__(self, values: Iterable[StatusState]=()) -> None:
        super().__init__(values)
        self.modifier_index = None

    def modifiers_for(self, key: str) -> Sequence[StatusState]:
        if self.modifier_index is None:
            self.build_indexes()
        return self.modifier_index.get(key, ())

    def named(self, name: str | None) -> Sequence[StatusState]:
        if self.modifier_index is None:
            self.build_indexes()
        return self.name_index.get(name, ())

    def with_rules(self) -> list[StatusState]:
        if self.modifier_index is None:
            self.build_indexes()
        return self.rule_states

    def build_indexes(self) -> None:
        index = self.modifier_index
        if index is None:
            index = {}
            names = {}
            rules = []
            reference = weakref.ref(self)
            for status in self:
                status.subscribe_modifiers(id(self), reference)
                names.setdefault(status.name, []).append(status)
                if status.rules:
                    rules.append(status)
                for attribute in status.modifiers:
                    index.setdefault(attribute, []).append(status)
            self.name_index = names
            self.rule_states = rules
            self.modifier_index = index

    def __setitem__(self, key: int | slice, value: StatusState | Iterable[StatusState]) -> None:
        self.modifier_index = None
        super().__setitem__(key, value)

    def __delitem__(self, key: int | slice) -> None:
        self.modifier_index = None
        super().__delitem__(key)

    def append(self, value: StatusState) -> None:
        super().append(value)
        if self.modifier_index is not None:
            value.subscribe_modifiers(id(self), weakref.ref(self))
            self.name_index.setdefault(value.name, []).append(value)
            if value.rules:
                self.rule_states.append(value)
            for attribute in value.modifiers:
                self.modifier_index.setdefault(attribute, []).append(value)

    def extend(self, values: Iterable[StatusState]) -> None:
        self.modifier_index = None
        super().extend(values)

    def insert(self, index: int, value: StatusState) -> None:
        self.modifier_index = None
        super().insert(index, value)

    def pop(self, index: int=-1) -> StatusState:
        self.modifier_index = None
        return super().pop(index)

    def remove(self, value: StatusState) -> None:
        self.modifier_index = None
        super().remove(value)

    def clear(self) -> None:
        self.modifier_index = None
        super().clear()

    def reverse(self) -> None:
        self.modifier_index = None
        super().reverse()

    def sort(self, *args: object, **kwargs: object) -> None:
        self.modifier_index = None
        super().sort(*args, **kwargs)

    def __iadd__(self, values: Iterable[StatusState]) -> StatusList:
        self.extend(values)
        return self

    def __imul__(self, count: int) -> StatusList:
        self.modifier_index = None
        super().__imul__(count)
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> StatusList:
        result = StatusList()
        memo[id(self)] = result
        result.extend(copy.deepcopy(value, memo) for value in self)
        return result


class SnapshotState:
    """为事务保存浅层字段状态；赋值自动失效，不要求执行器额外打脏标记。"""

    __slots__ = ("_snapshot_cache",)

    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, "_snapshot_cache", None)
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str | None) -> None:
        object.__setattr__(self, "_snapshot_cache", None)
        object.__delattr__(self, name)

    def __deepcopy__(self, memo: dict[int, Any]) -> SnapshotState:
        # 快照与索引订阅只属于原实例；不能经由 deepcopy 串到另一个战场。
        result = type(self).__new__(type(self))
        memo[id(self)] = result
        result.__dict__.update(copy.deepcopy(self.__dict__, memo))
        for base in type(self).__mro__:
            slots = base.__dict__.get("__slots__", ())
            for name in (slots,) if isinstance(slots, str) else slots:
                if name not in {"__dict__", "__weakref__", "_snapshot_cache", "_modifier_subscribers"} and hasattr(self, name):
                    object.__setattr__(result, name, copy.deepcopy(getattr(self, name), memo))
        return result

    def snapshot_state(self) -> tuple[type[SnapshotState], dict[str, object]]:
        cached = getattr(self, "_snapshot_cache", None)
        if cached is None:
            cached = (type(self), dict(self.__dict__))
            object.__setattr__(self, "_snapshot_cache", cached)
        return cached


@dataclass
class StatusState(SnapshotState):
    __slots__ = ("_modifier_subscribers", "__dict__", "__weakref__")

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"modifiers", "rules", "name"}:
            for reference in tuple(getattr(self, "_modifier_subscribers", {}).values()):
                collection = reference()
                if collection is not None:
                    collection.modifier_index = None
            if name != "name" and not isinstance(value, ModifierMap):
                value = ModifierMap(value)
        super().__setattr__(name, value)

    def subscribe_modifiers(self, key: int, reference: weakref.ReferenceType[StatusList]) -> None:
        subscribers = getattr(self, "_modifier_subscribers", None)
        if subscribers is None:
            subscribers = {}
            object.__setattr__(self, "_modifier_subscribers", subscribers)
        subscribers[key] = reference
        self.modifiers.subscribers[key] = reference
        self.rules.subscribers[key] = reference

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

    #: 浅拷走快路径（见 `_shallow_clone`）：回滚时逐个状态要拷，通用路太贵。
    __copy__ = _shallow_clone

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
        fields = dict(
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

        if cls is not StatusState:
            return cls(**fields)
        fields['modifiers'] = ModifierMap(fields['modifiers'])
        fields['rules'] = ModifierMap()
        status = cls.__new__(cls)
        status.__dict__.update(fields)
        return status

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
class Skill(SnapshotState):
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

    #: 浅拷走快路径（见 `_shallow_clone`）：回滚时逐个技能要拷，通用路太贵。
    __copy__ = _shallow_clone

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


class RuntimeExtensions:
    """为有固定热字段的运行模型保留扩展属性字典。"""


@dataclass(slots=True)
class Fighter(RuntimeExtensions):
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

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "statuses" and not isinstance(value, StatusList):
            value = StatusList(value)
        object.__setattr__(self, name, value)

    def value(self, key: str, default: float = 0.0) -> float:
        # 这一条是全战斗最热的读法（每次算血气上限都走它）：循环里不放 `max()` 与
        # `float()`，没有这个键的状态直接跳过——语义与原来逐字一致。
        result = self.attributes.get(key, default)
        # 无状态修正时属性读取是纯字典查找；这是战斗中最常见的读取形态。
        # 保持与下面带状态路径相同的数值类型归一化。
        if not self.statuses:
            return result if type(result) is float else float(result)
        for status in self.statuses.modifiers_for(key):
            modifier = status.modifiers.get(key)
            if modifier:
                stacks = status.stacks
                result += modifier * (stacks if stacks > 1 else 1)
        # 已经是 `float` 就直接还，省掉一次 C 层 `float()`——**同值、同类型、同字面**：
        # `float(x)` 对 `float` 实例返回的就是它本身；`int`（含 `default` 是整数那种）照旧
        # 走 `float()`，`bool` 与 `float` 子类被 `type(...) is float` 挡在外面、也照旧。
        # 实测（合成数据、96 万次/读数、3 轮中位）370.0 → 351.6 ms · **1.05×**、单次省 ~20 ns；
        # 真实调用量 475,339 次 ⇒ 约 9.5 ms ≈ 0.7%；等价自检 20 组「同值同类型同字面 不符 0 处」。
        if type(result) is float:
            return result
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

    # 属性定义来自启动期加载的只读目录；此函数只读取“默认值”，无需在每次
    # 百分比属性结算时复制整份定义字典。
    definition = (definitions or {}).get(attribute) or {}
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


@dataclass(slots=True)
class EventFrame(RuntimeExtensions):
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
        """事件当前数值。

        **默认值参数是立即求值的**：写成 `facts.get("当前数值", facts.get("实际数值", 0.0))`
        时，哪怕「当前数值」就在（绝大多数事件都在），内层那次 `get` 也白算一遍。所以这里先
        只查一次，缺了才去查「实际数值」。末尾那次 `float()` 同理——值本来就是 `float` 时不必
        再走一遍构造。

        实测（同一批真实帧交替三轮）：**223.8 → 151.7 ns · 1.475×**，逐次返回值与类型**全等**
        （23,887 / 23,887）。
        """

        try:
            value = self.facts["当前数值"]
        except KeyError:
            value = self.facts.get("实际数值", 0.0)
        return value if type(value) is float else float(value or 0.0)


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


@dataclass(slots=True)
class BattleContext(RuntimeExtensions):
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
    #: 结算实际派发并记录的事件总数；可大于 ``len(events)``，因为战报模式会
    #: 按数据目录跳过仅供内部流程使用的事件对象构建。
    event_count: int = 0
    #: None 表示保留全部；否则是战报模式要从事件轨迹中省略的展示隐藏类型。
    event_capture_filter: frozenset[str] | None = None
    event_capture_zero_change_kinds: frozenset[str] = frozenset()
    action_number: int = 0
    engine: BattleEngine | None = None
    #: 键是（修士 id, 词条, 监听声明）；键长不固定，所以用变长元组。
    #: 追加攻击也往这里记账，它用的是（来源 id, "追加攻击"）。
    trigger_counts: dict[tuple[str, ...], int] = dataclass_field(default_factory=dict)
    # 高频辅助监听的“持有者行动间隔”预算；按持有者下一次主行动前清理。
    support_window: dict[tuple[str, ...], int] = dataclass_field(default_factory=dict)
    battle_trigger_counts: dict[tuple[str, ...], int] = dataclass_field(default_factory=dict)
    #: 监听刚耗尽触发名额时递增；供候选表复用“仍可触发”的筛选结果。
    listener_budget_version: int = 0
    chain_serial: int = 0
    chain_active: bool = False
    chain_level: int = 1
    chain_counts: dict[tuple[str, ...], int] = dataclass_field(default_factory=dict)
    chain_exhausted: set[tuple[str, ...]] = dataclass_field(default_factory=set)
    chain_source_counts: dict[tuple[tuple[str, ...], str], int] = dataclass_field(default_factory=dict)
    chain_pending: list = dataclass_field(default_factory=list)
    chain_queued: set = dataclass_field(default_factory=set)
    battle_rule_serial: int = 0
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
    listener_fighter_order: dict[str, tuple[int, int]] = dataclass_field(default_factory=dict, init=False, repr=False)
    _fighters_cache: tuple[Fighter, ...] = dataclass_field(default_factory=tuple, init=False, repr=False)
    listener_index: dict[str, tuple[ListenerEntry, ...]] = dataclass_field(
        default_factory=dict, init=False, repr=False
    )
    #: 监听分桶：`事件 → (观察角色, 阵营关系) → 持有者 → [(位次, 监听条目)]`。
    #: 派发时按「阵营关系」把候选收到当事人身上，再按位次合并——顺序与 `listener_index` 逐条一致。
    listener_buckets: dict = dataclass_field(default_factory=dict, init=False, repr=False)
    listener_roles: dict = dataclass_field(default_factory=dict, init=False, repr=False)
    #: 监听表里**纯静态段**（修士被动）的编译结果：`持有者编号 → (被动表, 参与者位次, 事件 → 条目)`。
    #: 内容只由装配期的被动表与参与者位次决定，所以一场里重编 30~60 遍的那部分可以直接回放
    #: （见 `AbilityRuntime._passive_listener_entries`）。
    listener_passive_cache: dict = dataclass_field(default_factory=dict, init=False, repr=False)
    listener_passive_index: tuple[tuple[str, Mapping[str, tuple], tuple, tuple[int, int]], ...] | None = dataclass_field(default=None, init=False, repr=False)
    listener_index_dirty: bool = dataclass_field(default=True, init=False, repr=False)
    #: `_listeners_for` 的**候选表缓存**：`"table"` 存当时那份监听表对象，其余键是
    #: `(事件种类, 来源 id, 承受者 id, 行动者 id, 响应等级)`，值是 `(三个当事人, 候选表)`（命中时逐个核身份）。
    #: 重编后只保留成员关系与监听顺序均未变的事件候选，首次命中再刷新版本。
    listener_candidate_cache: dict = dataclass_field(default_factory=dict, init=False, repr=False)
    listener_membership: tuple = dataclass_field(default_factory=tuple, init=False, repr=False)
    #: 随监听表重建的最高响应等级；空调度仍记录事件，不抑制原子行为。
    listener_max_levels: dict[str, int] = dataclass_field(default_factory=dict, init=False, repr=False)
    #: `_dispatch_event` 的**节点字段缓存**：键是 `id(节点)`，值是
    #: `(节点, 条件, 每次行动最多触发, 每场战斗最多触发, 效果)`——命中时再核 `节点 is 原节点`，
    #: 所以 `id` 被复用也不会误用。这三样只是节点的**纯函数**，而同一个节点在这条事件的每个
    #: 候补、以及整场战斗的多次派发上会被反复问；与 `CombatCatalog._node_cache` 同一手法、
    #: 同一前提（节点在装配期冻结、一场里不换）。**加新的「每候选都要读的节点字段」时，
    #: 一并加进这个元组的末尾**（读处按位置解包，见 `_dispatch_event`）。
    node_field_cache: dict = dataclass_field(default_factory=dict, init=False, repr=False)
    #: `_conditions_allow` 的**条件执行器缓存**：键 `id(条件序列)`，值 `(条件序列, 执行器元组)`。
    #: 条件序列来自装配期冻结的内容，执行器只是它的**纯函数**，整批算一次与逐条现问等价。
    #: ⚠️ **调用方可能拿到 `context=None`**：规则层有「没有战斗现场也问一遍条件」的用法
    #: （第 29 步第一次改时就是在这里踩空，被 `tools/全量核对.py` 的「规则层行为」拦下），
    #: 所以读这张表的代码**必须先判空**，没有 context 就退回逐条现算（见 `_conditions_allow`）。
    condition_executor_cache: dict = dataclass_field(default_factory=dict, init=False, repr=False)
    #: `_execute_mechanism` 的**效果节点解析缓存**：键 `id(效果节点)`，值是 `RuleNode`——
    #: 命中时核 `node.values is 原节点`。执行器只是节点的**纯函数**（`parse_node` 自己就按身份
    #: 缓存），这里省掉的是**纯调用开销**（实测 13,259 次调用里 11,001 次命中、现场 10.9 ms）。
    #: 节点来自装配期冻结的内容；交给处理器的仍是 `dict(effect)` 副本，缓存不碰那份副本。
    ability_node_cache: dict = dataclass_field(default_factory=dict, init=False, repr=False)
    #: 效果节点对应的执行器函数缓存；与节点缓存使用同一对象身份护栏。
    ability_handler_cache: dict = dataclass_field(default_factory=dict, init=False, repr=False)
    #: 高频效果执行器的静态字段缓存，按节点对象身份核验。
    ability_static_cache: dict = dataclass_field(default_factory=dict, init=False, repr=False)
    #: 按标量属性配比复用规范化构成，不强引用临时效果节点。
    element_composition_cache: dict = dataclass_field(default_factory=dict, init=False, repr=False)
    element_multiplier_cache: dict[str, float] = dataclass_field(default_factory=dict, init=False, repr=False)
    target_selector_cache: dict = dataclass_field(default_factory=dict, init=False, repr=False)
    definition_copy_cache: dict = dataclass_field(default_factory=dict, init=False, repr=False)
    status_definition_cache: dict = dataclass_field(default_factory=dict, init=False, repr=False)
    #: 监听表的**版本号**：每次真重建（`_compiled_listeners` 换掉 `listener_index` 对象）就 +1。
    #: 候选表缓存里那份「按关系判定筛过」的候选表带的就是这个号；派发循环逐候选比一次，
    #: 号一变就退回逐条判定——因为**判定要读 `owner.side`**，而换阵营会重排位次、换表。
    listener_table_version: int = dataclass_field(default=0, init=False, repr=False)
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
        # 与全局位次同序；己方追加召唤物时，敌方的键保持不变。
        self.listener_fighter_order = {
            fighter.id: (side, index)
            for side, team in enumerate((self.left_team, self.right_team))
            for index, fighter in enumerate(team)
        }
        # 立即使当前派发的关系判定失效，但保留旧表供惰性重编逐项比对。
        # 回滚后的成员和监听若完全没变，可以复用对应事件的候选；入场、
        # 换阵营或监听变化仍由 _compiled_listeners 的成员/条目核对淘汰。
        self.mark_listener_index_dirty()

    def mark_listener_index_dirty(self) -> None:
        """结构动了：监听表要重编，**顺手把「已筛」戳的版本号也推一格**。

        `listener_table_version` 是候选表缓存里那份「已按关系判定筛过」的表的有效期。换阵营
        （或入场 / 状态进出 / 回滚）会改 `owner.side`，而判定正是读它，所以这类信号必须
        **当场**自增——`_compiled_listeners` 那趟重建是**懒**的，而派发循环会在这趟重建发生
        之前就拿版本号比一次；只在重建处自增的话，同一趟循环中途换阵营会被误判成「没换」，
        于是跳过本该重做的判定。宁可多作废（只慢不错）。
        """

        self.listener_index_dirty = True
        self.listener_table_version += 1

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
        # 第二处记录口（战场形成 / 阵法 / 地势这些由引擎直接派发的事件）：与
        # `mechanics._dispatch_event` 走同一份筛选，不然这些事件会带着整本账进日志。
        recorded = self.engine.recorded_facts if self.engine is not None else None
        self.event_count += 1
        if self.event_capture_filter is None or kind not in self.event_capture_filter:
            self.events.append(
                BattleEvent(
                    self.action_number,
                    kind,
                    source.name,
                    target.name,
                    text,
                    round(float(event_values.get("实际数值", event_values.get("当前数值", amount)) or 0), 3),
                    record_values(recorded, event_values),
                    tuple(tags),
                    ability,
                    source.id,
                    target.id,
                )
            )
        return frame
