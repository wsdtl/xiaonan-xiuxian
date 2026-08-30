"""由 JSON 驱动的玩家多类型状态服务。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from game.core.data import JsonDataService, materialize
from game.core.database import (
    DatabaseService,
    StateAddress,
    StateMutation,
    TransactionCommand,
)

from .contracts import (
    PlayerStateCharacterMissingError,
    PlayerStateConflictError,
    PlayerStateRuleError,
    PlayerStateServiceStatus,
    PlayerStateSnapshot,
    PublicPlayerState,
    StateContextUpdateCommand,
    StateGuardResult,
    StateSlot,
    StateTransitionCommand,
    StateTransitionPlan,
    StateTransitionResult,
)

STATE_TYPE = "player_state"
STATE_KEY = "main"
CHARACTER_STATE_TYPE = "character"
CHARACTER_STATE_KEY = "main"
STATE_TYPES = ("行为", "队伍", "控制")
STATE_FILES = {
    "行为": "行为状态",
    "队伍": "队伍状态",
    "控制": "控制状态",
}
CHARACTER_REQUIREMENTS = frozenset({"不限", "未创建", "已创建"})


class PlayerStateService:
    """解释状态定义、检查守卫并原子更新三槽快照。"""

    state_types = frozenset({STATE_TYPE})

    def __init__(self, data: JsonDataService, database: DatabaseService) -> None:
        self._data = data
        self._database = database
        self._initialized = False
        self._initial_states: Mapping[str, str] = MappingProxyType({})
        self._states: Mapping[str, Mapping[str, Mapping[str, Any]]] = MappingProxyType(
            {}
        )
        self._state_types_by_id: Mapping[str, str] = MappingProxyType({})
        self._guard_rules: Mapping[str, Mapping[str, Any]] = MappingProxyType({})

    def initialize(self) -> PlayerStateServiceStatus:
        if self._initialized:
            raise RuntimeError("玩家状态核心微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据服务必须先于玩家状态服务启动")
        if not self._database.status().initialized:
            raise RuntimeError("核心数据库必须先于玩家状态服务启动")

        documents = self._data.dataset("人物状态规则")
        states = {
            state_type: _index_states(
                documents.get(file_name),
                f"{file_name}.json",
            )
            for state_type, file_name in STATE_FILES.items()
        }
        initial_states = _mapping(documents.get("初始状态"), "初始状态.json")
        guard_rules = _index_guard_rules(documents.get("状态守卫"))
        self._validate_definition(states, initial_states, guard_rules)

        state_types_by_id = {
            state_id: state_type
            for state_type, entries in states.items()
            for state_id in entries
        }
        self._initial_states = MappingProxyType(
            {state_type: str(initial_states[state_type]) for state_type in STATE_TYPES}
        )
        self._states = MappingProxyType(
            {
                state_type: MappingProxyType(
                    {
                        state_id: MappingProxyType(materialize(rule))
                        for state_id, rule in entries.items()
                    }
                )
                for state_type, entries in states.items()
            }
        )
        self._state_types_by_id = MappingProxyType(state_types_by_id)
        self._guard_rules = MappingProxyType(
            {
                name: MappingProxyType(materialize(rule))
                for name, rule in guard_rules.items()
            }
        )
        self._initialized = True
        return self.status()

    def status(self) -> PlayerStateServiceStatus:
        return PlayerStateServiceStatus(
            initialized=self._initialized,
            initial_states=self._initial_states,
            state_count=sum(len(states) for states in self._states.values()),
            guard_rule_count=len(self._guard_rules),
        )

    def state_type(self, state_id: str) -> str:
        """返回一个状态编号所属的状态槽类型。"""

        self._require_initialized()
        normalized = _text(state_id, "状态编号")
        try:
            return self._state_types_by_id[normalized]
        except KeyError as exc:
            raise PlayerStateRuleError(f"未知状态编号：{normalized}") from exc

    def initial_mutation(self, user_id: str) -> StateMutation:
        """返回创建人物总事务所需的三槽初始快照。"""

        self._require_initialized()
        value = {
            state_type: {"状态编号": state_id, "上下文": {}}
            for state_type, state_id in self._initial_states.items()
        }
        return StateMutation(user_id, STATE_TYPE, STATE_KEY, value, 0)

    def validate_guard_rule(self, rule_name: str) -> None:
        """供统一启动契约校验命令引用。"""

        self._require_initialized()
        normalized = _text(rule_name, "状态守卫规则")
        if normalized not in self._guard_rules:
            raise PlayerStateRuleError(f"未知状态守卫规则：{normalized}")

    async def current(self, user_id: str) -> PlayerStateSnapshot | None:
        self._require_initialized()
        snapshot = await self._database.get(
            StateAddress(user_id, STATE_TYPE, STATE_KEY)
        )
        if snapshot is None:
            return None
        slots = self._parse_snapshot(snapshot.value)
        return PlayerStateSnapshot(
            user_id=user_id,
            states=MappingProxyType(slots),
            version=snapshot.version,
            updated_at=snapshot.updated_at,
        )

    async def public_many(
        self, user_ids: tuple[str, ...]
    ) -> tuple[PublicPlayerState, ...]:
        """批量返回附近展示所需的公开状态，不执行逐人物读取。"""

        self._require_initialized()
        normalized = _user_ids(user_ids)
        snapshots = await self._database.get_many(
            tuple(
                StateAddress(user_id, STATE_TYPE, STATE_KEY) for user_id in normalized
            )
        )
        by_user = {snapshot.address.user_id: snapshot for snapshot in snapshots}
        result: list[PublicPlayerState] = []
        for user_id in normalized:
            snapshot = by_user.get(user_id)
            if snapshot is None:
                continue
            slots = self._parse_snapshot(snapshot.value)
            behavior = slots["行为"]
            appears = bool(self._states["行为"][behavior.state_id]["附近出现"])
            names = tuple(
                slot.name
                for state_type, slot in slots.items()
                if bool(self._states[state_type][slot.state_id]["附近公开"])
            )
            result.append(PublicPlayerState(user_id, appears, names))
        return tuple(result)

    async def current_many(
        self, user_ids: tuple[str, ...]
    ) -> tuple[PlayerStateSnapshot, ...]:
        """批量返回通用三槽快照，不解释任何玩法上下文。"""

        self._require_initialized()
        normalized = _user_ids(user_ids)
        snapshots = await self._database.get_many(
            tuple(
                StateAddress(user_id, STATE_TYPE, STATE_KEY) for user_id in normalized
            )
        )
        by_user = {snapshot.address.user_id: snapshot for snapshot in snapshots}
        return tuple(
            PlayerStateSnapshot(
                user_id,
                MappingProxyType(self._parse_snapshot(snapshot.value)),
                snapshot.version,
                snapshot.updated_at,
            )
            for user_id in normalized
            if (snapshot := by_user.get(user_id)) is not None
        )

    async def plan_context_update(
        self, command: StateContextUpdateCommand
    ) -> StateTransitionPlan:
        """保持状态编号不变，只更新一个状态槽的业务上下文。"""

        self._require_initialized()
        state_type = _state_type(command.state_type)
        expected_state_id = _text(command.expected_state_id, "预期状态编号")
        if self._state_types_by_id.get(expected_state_id) != state_type:
            raise PlayerStateRuleError(
                f"{state_type}不存在状态编号：{expected_state_id}"
            )
        snapshot = await self.current(command.user_id)
        if snapshot is None:
            raise PlayerStateCharacterMissingError("尚未创建人物")
        current_slot = snapshot.states[state_type]
        if current_slot.state_id != expected_state_id:
            raise PlayerStateConflictError(
                f"{state_type}状态已经从{self._states[state_type][expected_state_id]['名称']}"
                f"变为{current_slot.name}"
            )
        value = self._snapshot_value(snapshot)
        value[state_type] = {
            "状态编号": current_slot.state_id,
            "上下文": materialize(_mapping(command.context, "玩家状态上下文")),
        }
        expected_version = (
            snapshot.version
            if command.expected_version is None
            else command.expected_version
        )
        return StateTransitionPlan(
            user_id=command.user_id,
            state_type=state_type,
            previous_state_id=current_slot.state_id,
            current_state_id=current_slot.state_id,
            mutation=StateMutation(
                command.user_id,
                STATE_TYPE,
                STATE_KEY,
                value,
                expected_version,
            ),
        )

    async def authorize(self, user_id: str, rule_name: str) -> StateGuardResult:
        """按人物是否存在及三个状态槽的组合规则判断命令准入。"""

        self._require_initialized()
        normalized_rule = _text(rule_name, "状态守卫规则")
        rule = self._guard_rules.get(normalized_rule)
        if rule is None:
            raise PlayerStateRuleError(f"未知状态守卫规则：{normalized_rule}")

        character_requirement = str(rule["人物要求"])
        state_requirements = _mapping(
            rule["状态要求"], f"状态守卫.{normalized_rule}.状态要求"
        )
        resource_requirements = _mapping(
            rule.get("资源要求", {}), f"状态守卫.{normalized_rule}.资源要求"
        )
        if character_requirement == "不限" and not state_requirements and not resource_requirements:
            return StateGuardResult(True)

        character = await self._database.get(
            StateAddress(user_id, CHARACTER_STATE_TYPE, CHARACTER_STATE_KEY)
        )
        snapshot = await self.current(user_id)
        if (character is None) != (snapshot is None):
            raise PlayerStateRuleError("人物与玩家状态快照不完整，请联系管理者处理")

        if character_requirement == "未创建":
            if character is None:
                return StateGuardResult(True)
            return StateGuardResult(False, "已经创建人物")
        if character_requirement == "已创建" and character is None:
            return StateGuardResult(False, "尚未创建人物")
        if snapshot is None:
            return StateGuardResult(True)

        current_names = MappingProxyType(
            {state_type: slot.name for state_type, slot in snapshot.states.items()}
        )
        failures: list[str] = []
        for state_type, raw_allowed in state_requirements.items():
            allowed = _strings(raw_allowed, f"状态守卫.{normalized_rule}.{state_type}")
            current_slot = snapshot.states[state_type]
            if current_slot.state_id in allowed:
                continue
            allowed_names = "或".join(
                self._states[state_type][state_id]["名称"] for state_id in allowed
            )
            failures.append(
                self._guard_failure_reason(
                    user_id,
                    state_type,
                    current_slot,
                    allowed_names,
                )
            )
        if character is not None:
            resources = _mapping(
                character.value.get("资源", {}), "人物.资源"
            )
            for resource_name, raw_requirement in resource_requirements.items():
                requirement = _mapping(
                    raw_requirement,
                    f"状态守卫.{normalized_rule}.资源要求.{resource_name}",
                )
                threshold = _nonnegative_number(
                    requirement.get("大于"),
                    f"状态守卫.{normalized_rule}.资源要求.{resource_name}.大于",
                )
                current = _nonnegative_number(
                    resources.get(resource_name), f"人物.资源.{resource_name}"
                )
                if current <= threshold:
                    failures.append(
                        "血气已经耗尽，请先闭关恢复后再行动"
                        if resource_name == "血气"
                        else f"{resource_name}不足，当前无法行动"
                    )
        if failures:
            return StateGuardResult(False, "；".join(failures), current_names)
        return StateGuardResult(True, current_states=current_names)

    def _guard_failure_reason(
        self,
        user_id: str,
        state_type: str,
        slot: StateSlot,
        allowed_names: str,
    ) -> str:
        if state_type != "行为":
            return f"{state_type}为{slot.name}，需要{allowed_names}"
        activity = self._states[state_type][slot.state_id].get("活动提示")
        if not isinstance(activity, Mapping):
            return f"{state_type}为{slot.name}，需要{allowed_names}"
        activity_name = str(activity.get("活动") or "").strip()
        progress_command = str(activity.get("进度命令") or "").strip()
        owner = str(slot.context.get("发起者") or "").strip()
        participant_count = slot.context.get("参与人数", 1)
        grouped = (
            isinstance(participant_count, int)
            and not isinstance(participant_count, bool)
            and participant_count > 1
        )
        if owner and owner != user_id:
            current = f"正在跟随领队{activity_name}"
        elif grouped:
            current = f"正在带领同行修士{activity_name}"
        else:
            current = f"正在{activity_name}"
        return f"{current}。当前不能执行该行动，可使用“{progress_command}”查看进度"

    async def transition(
        self, command: StateTransitionCommand
    ) -> StateTransitionResult:
        """校验并提交一个状态槽变化；调用方可用 expected_version 防止并发覆盖。"""

        plan = await self.plan_transition(command)
        receipt = await self._database.commit(
            TransactionCommand(
                user_id=command.user_id,
                request_id=command.request_id,
                business_type=f"玩家状态:{plan.state_type}变更",
                operations=(plan.mutation,),
                payload={
                    "状态类型": plan.state_type,
                    "前状态": plan.previous_state_id,
                    "后状态": plan.current_state_id,
                },
            )
        )
        return StateTransitionResult(
            user_id=command.user_id,
            state_type=plan.state_type,
            previous_state_id=plan.previous_state_id,
            current_state_id=plan.current_state_id,
            version=plan.mutation.expected_version + 1,
            replayed=receipt.replayed,
        )

    async def plan_transition(
        self, command: StateTransitionCommand
    ) -> StateTransitionPlan:
        """校验状态转换并只返回可并入跨领域事务的变更。"""

        self._require_initialized()
        state_type = _state_type(command.state_type)
        target_state_id = _text(command.target_state_id, "目标状态编号")
        if self._state_types_by_id.get(target_state_id) != state_type:
            raise PlayerStateRuleError(f"{state_type}不存在状态编号：{target_state_id}")
        snapshot = await self.current(command.user_id)
        if snapshot is None:
            raise PlayerStateCharacterMissingError("尚未创建人物")
        current_slot = snapshot.states[state_type]
        if target_state_id == current_slot.state_id:
            raise PlayerStateConflictError(f"人物已经处于{current_slot.name}")
        allowed = _strings(
            self._states[state_type][current_slot.state_id].get("可转入"),
            f"{current_slot.name}.可转入",
        )
        if target_state_id not in allowed:
            target_name = str(self._states[state_type][target_state_id]["名称"])
            raise PlayerStateConflictError(
                f"{state_type}状态不能从{current_slot.name}转为{target_name}"
            )

        expected = (
            snapshot.version
            if command.expected_version is None
            else command.expected_version
        )
        value = self._snapshot_value(snapshot)
        value[state_type] = {
            "状态编号": target_state_id,
            "上下文": materialize(_mapping(command.context, "玩家状态上下文")),
        }
        return StateTransitionPlan(
            user_id=command.user_id,
            state_type=state_type,
            previous_state_id=current_slot.state_id,
            current_state_id=target_state_id,
            mutation=StateMutation(
                command.user_id,
                STATE_TYPE,
                STATE_KEY,
                value,
                expected,
            ),
        )

    async def plan_finish_behavior(
        self,
        user_id: str,
        *,
        expected_version: int | None = None,
    ) -> StateTransitionPlan:
        """按当前行为的结束目标只生成状态变更。"""

        snapshot = await self.current(user_id)
        if snapshot is None:
            raise PlayerStateCharacterMissingError("尚未创建人物")
        current = snapshot.states["行为"]
        target = self._states["行为"][current.state_id].get("结束后")
        if target is None:
            raise PlayerStateConflictError(f"当前行为{current.name}不能结束")
        return await self.plan_transition(
            StateTransitionCommand(
                user_id=user_id,
                request_id="plan-only",
                state_type="行为",
                target_state_id=str(target),
                expected_version=(
                    snapshot.version if expected_version is None else expected_version
                ),
            )
        )

    async def finish_behavior(
        self,
        user_id: str,
        request_id: str,
        *,
        expected_version: int | None = None,
    ) -> StateTransitionResult:
        """按行为状态定义的结束目标完成当前行为。"""

        snapshot = await self.current(user_id)
        if snapshot is None:
            raise PlayerStateCharacterMissingError("尚未创建人物")
        current = snapshot.states["行为"]
        target = self._states["行为"][current.state_id].get("结束后")
        if target is None:
            raise PlayerStateConflictError(f"当前行为{current.name}不能结束")
        return await self.transition(
            StateTransitionCommand(
                user_id=user_id,
                request_id=request_id,
                state_type="行为",
                target_state_id=str(target),
                expected_version=(
                    snapshot.version if expected_version is None else expected_version
                ),
            )
        )

    async def interrupt_behavior(
        self,
        user_id: str,
        request_id: str,
        *,
        expected_version: int | None = None,
    ) -> StateTransitionResult:
        """仅在 JSON 允许时中断当前行为。"""

        snapshot = await self.current(user_id)
        if snapshot is None:
            raise PlayerStateCharacterMissingError("尚未创建人物")
        current = snapshot.states["行为"]
        if not bool(self._states["行为"][current.state_id].get("可中断")):
            raise PlayerStateConflictError(f"当前行为{current.name}不能中断")
        return await self.finish_behavior(
            user_id,
            request_id,
            expected_version=(
                snapshot.version if expected_version is None else expected_version
            ),
        )

    def _validate_definition(
        self,
        states: Mapping[str, Mapping[str, Mapping[str, Any]]],
        initial_states: Mapping[str, object],
        guard_rules: Mapping[str, Mapping[str, Any]],
    ) -> None:
        if set(states) != set(STATE_TYPES) or set(initial_states) != set(STATE_TYPES):
            raise PlayerStateRuleError("玩家状态必须完整定义行为、队伍和控制三种类型")

        seen_ids: set[str] = set()
        for state_type, entries in states.items():
            if not entries:
                raise PlayerStateRuleError(f"{state_type}状态不能为空")
            overlap = seen_ids & set(entries)
            if overlap:
                raise PlayerStateRuleError(
                    f"人物状态编号重复：{'、'.join(sorted(overlap))}"
                )
            seen_ids.update(entries)
            names: set[str] = set()
            for state_id, state in entries.items():
                name = _text(state.get("名称"), f"{state_type}.{state_id}.名称")
                if name in names:
                    raise PlayerStateRuleError(f"{state_type}状态名称重复：{name}")
                names.add(name)
                transitions = _strings(state.get("可转入"), f"{name}.可转入")
                unknown = set(transitions) - set(entries)
                if unknown:
                    raise PlayerStateRuleError(
                        f"{name}.可转入包含其他类型或未知状态：{'、'.join(sorted(unknown))}"
                    )
                if state_type == "行为":
                    ending = state.get("结束后")
                    if ending is not None and str(ending) not in entries:
                        raise PlayerStateRuleError(f"{name}.结束后不是行为状态")
                    if not isinstance(state.get("可中断"), bool):
                        raise PlayerStateRuleError(f"{name}.可中断必须是布尔值")
                    if not isinstance(state.get("附近出现"), bool):
                        raise PlayerStateRuleError(f"{name}.附近出现必须是布尔值")
                    activity = state.get("活动提示")
                    if activity is not None:
                        activity_rule = _mapping(activity, f"{name}.活动提示")
                        if set(activity_rule) != {"活动", "进度命令"}:
                            raise PlayerStateRuleError(
                                f"{name}.活动提示必须只包含活动和进度命令"
                            )
                        _text(activity_rule.get("活动"), f"{name}.活动提示.活动")
                        _text(
                            activity_rule.get("进度命令"),
                            f"{name}.活动提示.进度命令",
                        )
                if not isinstance(state.get("附近公开"), bool):
                    raise PlayerStateRuleError(f"{name}.附近公开必须是布尔值")

            initial = str(initial_states[state_type])
            if initial not in entries:
                raise PlayerStateRuleError(f"{state_type}初始状态不存在：{initial}")

        for name, rule in guard_rules.items():
            unknown_fields = set(rule) - {"名称", "人物要求", "状态要求", "资源要求"}
            if unknown_fields:
                raise PlayerStateRuleError(
                    f"状态守卫{name}包含未知字段：{'、'.join(sorted(unknown_fields))}"
                )
            requirement = _text(rule.get("人物要求"), f"状态守卫.{name}.人物要求")
            if requirement not in CHARACTER_REQUIREMENTS:
                raise PlayerStateRuleError(
                    f"状态守卫{name}使用未知人物要求：{requirement}"
                )
            requirements = _mapping(rule.get("状态要求"), f"状态守卫.{name}.状态要求")
            if requirement == "未创建" and requirements:
                raise PlayerStateRuleError(
                    f"状态守卫{name}不能要求未创建人物同时具有状态"
                )
            for state_type, raw_allowed in requirements.items():
                normalized_type = _state_type(state_type)
                allowed = _strings(raw_allowed, f"状态守卫.{name}.{normalized_type}")
                if not allowed:
                    raise PlayerStateRuleError(
                        f"状态守卫{name}.{normalized_type}不能为空"
                    )
                unknown = set(allowed) - set(states[normalized_type])
                if unknown:
                    raise PlayerStateRuleError(
                        f"状态守卫{name}.{normalized_type}包含未知状态：{'、'.join(sorted(unknown))}"
                    )
            resources = _mapping(
                rule.get("资源要求", {}), f"状态守卫.{name}.资源要求"
            )
            for resource_name, raw_requirement in resources.items():
                if resource_name not in {"血气", "精神"}:
                    raise PlayerStateRuleError(
                        f"状态守卫{name}使用未知人物资源：{resource_name}"
                    )
                resource_rule = _mapping(
                    raw_requirement, f"状态守卫.{name}.资源要求.{resource_name}"
                )
                if set(resource_rule) != {"大于"}:
                    raise PlayerStateRuleError(
                        f"状态守卫{name}.{resource_name}必须只定义大于"
                    )
                _nonnegative_number(
                    resource_rule.get("大于"),
                    f"状态守卫.{name}.资源要求.{resource_name}.大于",
                )

    def _parse_snapshot(self, value: Mapping[str, Any]) -> dict[str, StateSlot]:
        if set(value) != set(STATE_TYPES):
            raise PlayerStateRuleError("数据库玩家状态必须完整包含行为、队伍和控制")
        result: dict[str, StateSlot] = {}
        for state_type in STATE_TYPES:
            raw_slot = _mapping(value[state_type], f"玩家状态.{state_type}")
            state_id = _text(
                raw_slot.get("状态编号"), f"玩家状态.{state_type}.状态编号"
            )
            if self._state_types_by_id.get(state_id) != state_type:
                raise PlayerStateRuleError(
                    f"数据库中的{state_type}状态未定义：{state_id}"
                )
            context = materialize(
                _mapping(raw_slot.get("上下文", {}), f"玩家状态.{state_type}.上下文")
            )
            result[state_type] = StateSlot(
                state_type=state_type,
                state_id=state_id,
                name=str(self._states[state_type][state_id]["名称"]),
                context=MappingProxyType(context),
            )
        return result

    @staticmethod
    def _snapshot_value(snapshot: PlayerStateSnapshot) -> dict[str, Any]:
        return {
            state_type: {
                "状态编号": slot.state_id,
                "上下文": materialize(slot.context),
            }
            for state_type, slot in snapshot.states.items()
        }

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("玩家状态核心微服务尚未初始化")


def _index_states(value: object, label: str) -> dict[str, Mapping[str, Any]]:
    rows = _dictionary_list(value, label)
    result: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        state_id = _text(row.get("编号"), f"{label}[{index}].编号")
        if state_id in result:
            raise PlayerStateRuleError(f"{label}存在重复编号：{state_id}")
        result[state_id] = row
    return result


def _index_guard_rules(value: object) -> dict[str, Mapping[str, Any]]:
    rows = _dictionary_list(value, "状态守卫.json")
    result: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        name = _text(row.get("名称"), f"状态守卫.json[{index}].名称")
        if name in result:
            raise PlayerStateRuleError(f"状态守卫名称重复：{name}")
        result[name] = row
    return result


def _dictionary_list(value: object, label: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PlayerStateRuleError(f"{label}必须是字典列表")
    rows = tuple(value)
    if not rows or any(not isinstance(row, Mapping) for row in rows):
        raise PlayerStateRuleError(f"{label}必须是非空字典列表")
    return rows


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PlayerStateRuleError(f"{label}必须是对象")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlayerStateRuleError(f"{label}必须是非空字符串")
    return value.strip()


def _nonnegative_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlayerStateRuleError(f"{label}必须是非负数")
    result = float(value)
    if result < 0:
        raise PlayerStateRuleError(f"{label}必须是非负数")
    return result


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PlayerStateRuleError(f"{label}必须是字符串数组")
    result = tuple(_text(item, label) for item in value)
    if len(result) != len(set(result)):
        raise PlayerStateRuleError(f"{label}不能包含重复值")
    return result


def _state_type(value: object) -> str:
    normalized = _text(value, "状态类型")
    if normalized not in STATE_TYPES:
        raise PlayerStateRuleError(f"未知状态类型：{normalized}")
    return normalized


def _user_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(_text(value, "user_id") for value in values)
    if len(normalized) != len(set(normalized)):
        raise ValueError("user_id不能重复")
    return normalized


__all__ = ["STATE_KEY", "STATE_TYPE", "PlayerStateService"]
