"""解释 JSON 伤势并维护人物、道侣各自的长期伤势事实。"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType

from game.core.combat import BattleEvent, CombatantResult, CombatStatusSpec
from game.core.data import ContractSet, JsonDataError, JsonDataService, materialize
from game.core.database import DatabaseService, StateAddress, StateMutation

from .contracts import (
    InjuryChange,
    InjuryEntry,
    InjuryError,
    InjuryEvolution,
    InjurySource,
    InjuryState,
    InjuryStatus,
    InjurySummary,
    InjuryTreatment,
)

STATE_TYPE = "injury"
PLAYER_KEY = "player"


@dataclass(frozen=True)
class _Definition:
    injury_id: str
    name: str
    category: str
    realm_id: str
    match_status: str
    match_priority: int
    matcher: Mapping[str, object]
    trigger_priority: int
    trigger: Mapping[str, object]
    battle_status: Mapping[str, object]
    maximum_stacks: int
    treatment_rounds: int
    treatment_priority: int


class InjuryService:
    """长期伤势的唯一状态所有者。"""


    def __init__(self, data: JsonDataService, database: DatabaseService) -> None:
        self._data = data
        self._database = database
        self._initialized = False
        self._definitions: Mapping[str, _Definition] = MappingProxyType({})
        self._external_definitions: tuple[_Definition, ...] = ()
        self._self_by_realm: Mapping[str, tuple[_Definition, ...]] = MappingProxyType(
            {}
        )
        self._self_limit = 0
        self._source_limit = 0
        self._treatment_count = 0

    def initialize(self) -> InjuryStatus:
        if self._initialized:
            raise RuntimeError("长期伤势核心已经初始化")
        if not self._database.status().initialized:
            raise RuntimeError("核心数据库必须先于长期伤势核心启动")
        rules = _mapping(
            self._data.dataset("角色伤势规则").get("长期伤势"),
            "长期伤势.json",
        )
        self._self_limit = _positive_int(rules.get("每场自生上限"), "每场自生上限")
        self._source_limit = _positive_int(rules.get("来源记录上限"), "来源记录上限")
        treatment = _mapping(rules.get("闭关治疗"), "长期伤势.闭关治疗")
        self._treatment_count = _positive_int(
            treatment.get("每轮处理伤势数"), "闭关治疗.每轮处理伤势数"
        )
        if (
            treatment.get("恢复丹治疗") is not False
            or treatment.get("自然恢复") is not False
        ):
            raise JsonDataError("长期伤势只能通过闭关完整轮次治疗")
        # 治疗以完整轮次为单位，语义写在数据里（`闭关治疗.单位`），这里读死。
        if treatment.get("单位") != "完整轮次":
            raise JsonDataError("长期伤势闭关治疗必须以完整轮次为单位")

        contract = ContractSet.load(
            self._data.dataset("角色字段契约").get("角色字段契约"),
            "角色/规则/角色字段契约.json",
        )
        definitions = {}
        for injury_id, value in self._data.entities("伤势").items():
            contract.validate(value, "伤势", f"伤势 {injury_id}")
            definitions[injury_id] = self._definition(injury_id, value)
        external_values = tuple(
            sorted(
                (
                    value
                    for value in definitions.values()
                    if value.category == "外来伤势"
                ),
                key=lambda item: (item.match_priority, item.injury_id),
            )
        )
        if len({value.match_status for value in external_values}) != len(
            external_values
        ):
            raise JsonDataError("外来伤势的匹配状态不能重复")
        if sum(bool(value.matcher.get("兜底")) for value in external_values) != 1:
            raise JsonDataError("外来伤势必须恰好定义一个兜底归类")
        by_realm: dict[str, list[_Definition]] = defaultdict(list)
        for value in definitions.values():
            if value.category == "境界自生":
                by_realm[value.realm_id].append(value)
        expected = _positive_int(rules.get("每境界自生数量"), "每境界自生数量")
        realm_ids = set(self._data.entities("境界"))
        if set(by_realm) != realm_ids:
            raise JsonDataError("每个正式境界都必须拥有自生伤势")
        if any(len(values) != expected for values in by_realm.values()):
            raise JsonDataError(f"每个境界必须恰好拥有{expected}种自生伤势")

        self._definitions = MappingProxyType(definitions)
        self._external_definitions = external_values
        self._self_by_realm = MappingProxyType(
            {
                realm_id: tuple(
                    sorted(
                        values, key=lambda item: (item.trigger_priority, item.injury_id)
                    )
                )
                for realm_id, values in by_realm.items()
            }
        )
        self._initialized = True
        return self.status()

    def status(self) -> InjuryStatus:
        values = tuple(self._definitions.values())
        return InjuryStatus(
            self._initialized,
            len(values),
            sum(value.category == "外来伤势" for value in values),
            sum(value.category == "境界自生" for value in values),
        )

    async def state(self, user_id: str, subject_key: str) -> InjuryState:
        self._require_initialized()
        user = _text(user_id, "user_id")
        subject = _subject_key(subject_key)
        snapshot = await self._database.get(StateAddress(user, STATE_TYPE, subject))
        if snapshot is None:
            return InjuryState(user, subject, (), 0)
        return self.restore(
            snapshot.value, user_id=user, subject_key=subject, version=snapshot.version
        )

    def restore(
        self,
        value: Mapping[str, object],
        *,
        user_id: str,
        subject_key: str,
        version: int,
    ) -> InjuryState:
        self._require_initialized()
        raw = _mapping(value, "伤势状态")
        stored_subject = _subject_key(raw.get("主体"))
        if stored_subject != _subject_key(subject_key):
            raise InjuryError("伤势状态主体与状态键不一致")
        entries = tuple(
            self._entry(_mapping(item, "伤势状态.伤势[]"))
            for item in _sequence(raw.get("伤势", ()), "伤势状态.伤势")
        )
        if len({entry.injury_id for entry in entries}) != len(entries):
            raise InjuryError("同一主体的伤势编号不能重复保存")
        return InjuryState(
            _text(user_id, "user_id"), stored_subject, entries, int(version)
        )

    def serialize(self, state: InjuryState) -> dict[str, object]:
        self._require_initialized()
        return {
            "主体": state.subject_key,
            "伤势": [
                {
                    "编号": entry.injury_id,
                    "层数": entry.stacks,
                    "获得顺序": entry.acquired_order,
                    "疗养进度": entry.treatment_progress,
                    "来源": [
                        {
                            "战斗编号": source.battle_id,
                            "类别": source.category,
                            "来源编号": source.source_id,
                            "来源名称": source.source_name,
                        }
                        for source in entry.sources
                    ],
                }
                for entry in state.entries
            ],
        }

    def settlement_mutation(self, state: InjuryState) -> StateMutation:
        return StateMutation(
            state.user_id,
            STATE_TYPE,
            state.subject_key,
            self.serialize(state),
            state.version,
        )

    def prepared_statuses(self, state: InjuryState) -> tuple[CombatStatusSpec, ...]:
        self._require_initialized()
        result = []
        for entry in state.entries:
            definition = self._definitions[entry.injury_id]
            raw = definition.battle_status
            result.append(
                CombatStatusSpec(
                    name=definition.name,
                    category=_text(
                        raw.get("类别"), f"伤势 {entry.injury_id}.战斗状态.类别"
                    ),
                    remaining_actions=_positive_int(
                        raw.get("剩余行动"), f"伤势 {entry.injury_id}.战斗状态.剩余行动"
                    ),
                    duration_unit=_text(
                        raw.get("持续单位"), f"伤势 {entry.injury_id}.战斗状态.持续单位"
                    ),
                    modifiers=tuple(
                        (str(key), float(value))
                        for key, value in _mapping(
                            raw.get("属性", {}), f"伤势 {entry.injury_id}.战斗状态.属性"
                        ).items()
                    ),
                    tags=tuple(_texts(raw.get("标签", ()), "战斗状态.标签")),
                    listeners=tuple(
                        _mappings(raw.get("监听", ()), "战斗状态.监听")
                    ),
                    source=entry.injury_id,
                    source_name=definition.name,
                    metadata=(("伤势编号", entry.injury_id),),
                    stacks=entry.stacks,
                    maximum_stacks=definition.maximum_stacks,
                    action_limits=tuple(
                        _texts(raw.get("行动限制", ()), "战斗状态.行动限制")
                    ),
                )
            )
        return tuple(result)

    def evolve(
        self,
        state: InjuryState,
        *,
        realm_id: str,
        combatant_result: CombatantResult,
        events: Sequence[BattleEvent],
        enemy_ids: Sequence[str],
        battle_id: str,
    ) -> InjuryEvolution:
        self._require_initialized()
        enemies = frozenset(str(value) for value in enemy_ids)
        candidates: list[tuple[_Definition, InjurySource]] = []
        for status in combatant_result.statuses:
            definition = next(
                (
                    value
                    for value in self._external_definitions
                    if value.match_status == status.name
                    or self._matches_external(value.matcher, status)
                ),
                None,
            )
            if (
                definition is None
                or status.category != "负面"
                or status.remaining_turns <= 0
                or status.source not in enemies
            ):
                continue
            candidates.append(
                (
                    definition,
                    InjurySource(
                        _text(battle_id, "battle_id"),
                        "外来伤势",
                        status.source,
                        status.source_name,
                    ),
                )
            )
        self_definitions = [
            definition
            for definition in self._self_by_realm.get(_text(realm_id, "realm_id"), ())
            if self._triggered(definition.trigger, combatant_result, events)
        ][: self._self_limit]
        candidates.extend(
            (
                definition,
                InjurySource(
                    _text(battle_id, "battle_id"),
                    "境界自生",
                    combatant_result.id,
                    combatant_result.name,
                ),
            )
            for definition in self_definitions
        )
        return self._apply_candidates(state, candidates)

    @staticmethod
    def _matches_external(matcher: Mapping[str, object], status: str) -> bool:
        if matcher.get("兜底") is True:
            return True
        attributes = set(_texts(matcher.get("属性任一", ()), "外来伤势.匹配.属性任一"))
        limits = set(
            _texts(matcher.get("行动限制任一", ()), "外来伤势.匹配.行动限制任一")
        )
        tags = set(_texts(matcher.get("标签任一", ()), "外来伤势.匹配.标签任一"))
        return bool(
            attributes.intersection(status.modifiers)
            or limits.intersection(status.action_limits)
            or tags.intersection(status.tags)
        )

    async def plan_treatment(
        self, user_id: str, subject_key: str, completed_rounds: int
    ) -> InjuryTreatment:
        state = await self.state(user_id, subject_key)
        rounds = _nonnegative_int(completed_rounds, "闭关完整轮数")
        if not state.entries or rounds == 0:
            return InjuryTreatment(state, None, ())
        entries = {entry.injury_id: entry for entry in state.entries}
        changes: list[InjuryChange] = []
        for _ in range(rounds):
            for __ in range(self._treatment_count):
                if not entries:
                    break
                current = min(
                    entries.values(),
                    key=lambda entry: (
                        self._definitions[entry.injury_id].treatment_priority,
                        entry.acquired_order,
                        entry.injury_id,
                    ),
                )
                definition = self._definitions[current.injury_id]
                progress = current.treatment_progress + 1
                if progress < definition.treatment_rounds:
                    entries[current.injury_id] = replace(
                        current, treatment_progress=progress
                    )
                    continue
                after = current.stacks - 1
                changes.append(
                    InjuryChange(
                        current.injury_id,
                        current.name,
                        current.stacks,
                        after,
                        "闭关疗伤",
                    )
                )
                if after <= 0:
                    del entries[current.injury_id]
                else:
                    entries[current.injury_id] = replace(
                        current, stacks=after, treatment_progress=0
                    )
        after_state = replace(
            state,
            entries=tuple(
                sorted(entries.values(), key=lambda item: item.acquired_order)
            ),
        )
        return InjuryTreatment(
            after_state,
            self.settlement_mutation(after_state),
            tuple(changes),
        )

    def summary(self, state: InjuryState) -> InjurySummary:
        return InjurySummary(
            state.subject_key,
            tuple(
                MappingProxyType(
                    {
                        "编号": entry.injury_id,
                        "名称": entry.name,
                        "类别": entry.category,
                        "层数": entry.stacks,
                        "疗养进度": entry.treatment_progress,
                        "每层所需轮数": self._definitions[
                            entry.injury_id
                        ].treatment_rounds,
                    }
                )
                for entry in state.entries
            ),
        )

    def _apply_candidates(
        self,
        state: InjuryState,
        candidates: Sequence[tuple[_Definition, InjurySource]],
    ) -> InjuryEvolution:
        entries = {entry.injury_id: entry for entry in state.entries}
        order = max((entry.acquired_order for entry in entries.values()), default=0)
        changes: list[InjuryChange] = []
        seen: set[str] = set()
        for definition, source in candidates:
            if definition.injury_id in seen:
                continue
            seen.add(definition.injury_id)
            previous = entries.get(definition.injury_id)
            before = previous.stacks if previous else 0
            after = min(definition.maximum_stacks, before + 1)
            if previous is None:
                order += 1
                entries[definition.injury_id] = InjuryEntry(
                    definition.injury_id,
                    definition.name,
                    definition.category,
                    after,
                    order,
                    0,
                    (source,),
                )
            else:
                entries[definition.injury_id] = replace(
                    previous,
                    stacks=after,
                    sources=(*previous.sources, source)[-self._source_limit :],
                )
            if after != before:
                changes.append(
                    InjuryChange(
                        definition.injury_id,
                        definition.name,
                        before,
                        after,
                        definition.category,
                    )
                )
        return InjuryEvolution(
            replace(
                state,
                entries=tuple(
                    sorted(entries.values(), key=lambda item: item.acquired_order)
                ),
            ),
            tuple(changes),
        )

    @staticmethod
    def _triggered(
        trigger: Mapping[str, object],
        result: CombatantResult,
        events: Sequence[BattleEvent],
    ) -> bool:
        kind = str(trigger.get("类型") or "")
        if kind == "资源归零":
            resource = str(trigger.get("资源") or "")
            return (resource == "血气" and result.health <= 0) or (
                resource == "精神" and result.spirit <= 0
            )
        if kind != "事件累计":
            raise InjuryError(f"未知境界伤势触发类型：{kind or '<空>'}")
        event_name = _text(trigger.get("事件"), "伤势.触发.事件")
        role = _text(trigger.get("角色"), "伤势.触发.角色")
        required = _positive_int(trigger.get("次数"), "伤势.触发.次数")
        count = Counter(
            event.kind
            for event in events
            if (role == "来源" and event.source_id == result.id)
            or (role == "承受者" and event.target_id == result.id)
        )
        return count[event_name] >= required

    def _entry(self, value: Mapping[str, object]) -> InjuryEntry:
        injury_id = _text(value.get("编号"), "伤势状态.编号")
        definition = self._definitions.get(injury_id)
        if definition is None:
            raise InjuryError(f"伤势状态引用未知编号：{injury_id}")
        stacks = _positive_int(value.get("层数"), "伤势状态.层数")
        if stacks > definition.maximum_stacks:
            raise InjuryError(f"伤势 {injury_id} 层数超过定义上限")
        progress = _nonnegative_int(value.get("疗养进度", 0), "伤势状态.疗养进度")
        if progress >= definition.treatment_rounds:
            raise InjuryError(f"伤势 {injury_id} 疗养进度应已结算层数")
        sources = tuple(
            InjurySource(
                _text(raw.get("战斗编号"), "伤势来源.战斗编号"),
                _text(raw.get("类别"), "伤势来源.类别"),
                str(raw.get("来源编号") or "").strip(),
                str(raw.get("来源名称") or "").strip(),
            )
            for raw in (
                _mapping(item, "伤势状态.来源[]")
                for item in _sequence(value.get("来源", ()), "伤势状态.来源")
            )
        )
        return InjuryEntry(
            injury_id,
            definition.name,
            definition.category,
            stacks,
            _positive_int(value.get("获得顺序"), "伤势状态.获得顺序"),
            progress,
            sources[-self._source_limit :],
        )

    @staticmethod
    def _definition(injury_id: str, value: Mapping[str, object]) -> _Definition:
        raw = materialize(value)
        category = _text(raw.get("来源类别"), f"伤势 {injury_id}.来源类别")
        if category not in {"外来伤势", "境界自生"}:
            raise JsonDataError(f"伤势 {injury_id} 来源类别不合法")
        matcher = _mapping(raw.get("匹配", {}), "伤势.匹配")
        unknown_matchers = set(matcher) - {
            "属性任一",
            "行动限制任一",
            "标签任一",
            "兜底",
        }
        if unknown_matchers:
            raise JsonDataError(
                f"伤势 {injury_id} 使用未知匹配条件：{'、'.join(sorted(unknown_matchers))}"
            )
        if category == "外来伤势" and not matcher:
            raise JsonDataError(f"外来伤势 {injury_id} 必须定义实际负面状态匹配条件")
        if category == "境界自生" and matcher:
            raise JsonDataError(f"境界自生伤势 {injury_id} 不能定义外来状态匹配条件")
        return _Definition(
            injury_id,
            _text(raw.get("名称"), f"伤势 {injury_id}.名称"),
            category,
            str(raw.get("境界") or "").strip(),
            str(raw.get("匹配状态") or "").strip(),
            (
                _positive_int(raw.get("匹配优先级"), "伤势.匹配优先级")
                if category == "外来伤势"
                else 0
            ),
            MappingProxyType(matcher),
            int(raw.get("触发优先级") or 0),
            MappingProxyType(_mapping(raw.get("触发", {}), "伤势.触发")),
            MappingProxyType(_mapping(raw.get("战斗状态"), "伤势.战斗状态")),
            _positive_int(
                _mapping(raw.get("叠加"), "伤势.叠加").get("层数上限"), "伤势.层数上限"
            ),
            _positive_int(
                _mapping(raw.get("治疗"), "伤势.治疗").get("每层所需轮数"),
                "伤势.每层所需轮数",
            ),
            _positive_int(
                _mapping(raw.get("治疗"), "伤势.治疗").get("优先级"), "伤势.治疗优先级"
            ),
        )

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("长期伤势核心尚未初始化")


def companion_subject(companion_id: str) -> str:
    return f"companion:{_text(companion_id, '道侣编号')}"


def _subject_key(value: object) -> str:
    result = _text(value, "伤势主体")
    if result != PLAYER_KEY and not result.startswith("companion:"):
        raise InjuryError("伤势主体只能是人物或具体道侣")
    return result


def _mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{path} 必须是对象")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object, path: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise InjuryError(f"{path} 必须是数组")
    return tuple(value)


def _texts(value: object, path: str) -> tuple[str, ...]:
    return tuple(_text(item, f"{path}[]") for item in _sequence(value, path))


def _mappings(value: object, path: str) -> tuple[Mapping[str, object], ...]:
    return tuple(
        _mapping(item, f"{path}[]") for item in _sequence(value, path)
    )


def _text(value: object, path: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise InjuryError(f"{path} 不能为空")
    return result


def _positive_int(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InjuryError(f"{path} 必须是正整数")
    return value


def _nonnegative_int(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InjuryError(f"{path} 必须是非负整数")
    return value


__all__ = ["PLAYER_KEY", "STATE_TYPE", "InjuryService", "companion_subject"]
