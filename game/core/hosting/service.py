"""托管计划核心：持久化自定义循环并为本地驱动器生成单步命令。"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from types import MappingProxyType

from game.core.action_group import ActionGroupError, ActionGroupService
from game.core.data import JsonDataError, JsonDataService, materialize
from game.core.database import (
    DatabaseService,
    SharedEntityMutation,
    StateAddress,
    StateConflictError,
    StateMutation,
    TransactionCommand,
)
from game.core.player_state import PlayerStateService, StateTransitionCommand

from .contracts import (
    HostingActivity,
    HostingError,
    HostingExecution,
    HostingServiceStatus,
    HostingSession,
)

CONTROL_TYPE = "控制"
PLAN_ENTITY_TYPE = "托管计划"
LATEST_STATE = "hosting_latest"
LATEST_KEY = "main"
RUNNING = "运行中"
PAUSED = "已暂停"
WAIT_START = "待开始"
WAIT_END = "待结束"
EXECUTE_START = "执行开始"
EXECUTE_END = "执行结束"
PHASES = frozenset({WAIT_START, WAIT_END, EXECUTE_START, EXECUTE_END})


class HostingService:
    state_types = frozenset({LATEST_STATE})

    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService,
        player_state: PlayerStateService,
        action_group: ActionGroupService,
    ) -> None:
        self._data = data
        self._database = database
        self._player_state = player_state
        self._action_group = action_group
        self._initialized = False
        self._control_states: Mapping[str, str] = MappingProxyType({})
        self._mode_names: Mapping[str, str] = MappingProxyType({})
        self._role_names: Mapping[str, str] = MappingProxyType({})
        self._activities: Mapping[str, HostingActivity] = MappingProxyType({})
        self._context_fields = frozenset()
        self._activity_seconds = 0
        self._maximum_seconds = 0
        self._minimum_activities = 0
        self._maximum_activities = 0

    def initialize(self) -> HostingServiceStatus:
        if self._initialized:
            raise RuntimeError("托管核心微服务已经初始化")
        if not self._database.status().initialized:
            raise RuntimeError("核心数据库必须先于托管核心启动")
        if not self._player_state.status().initialized:
            raise RuntimeError("玩家状态核心必须先于托管核心启动")
        if not self._action_group.status().initialized:
            raise RuntimeError("行动编排核心必须先于托管核心启动")

        rule = _mapping(self._data.dataset("托管规则").get("托管"), "托管.json")
        control_states = _string_mapping(rule.get("控制状态"), "托管.控制状态")
        mode_names = _string_mapping(rule.get("同行类型"), "托管.同行类型")
        role_names = _string_mapping(rule.get("托管身份"), "托管.托管身份")
        context_fields = frozenset(_strings(rule.get("上下文字段"), "托管.上下文字段"))
        activity_seconds = _positive_int(rule.get("活动时长秒数"), "托管.活动时长秒数")
        maximum_seconds = _positive_int(
            rule.get("单次托管最长秒数"), "托管.单次托管最长秒数"
        )
        combination = _mapping(rule.get("组合规则"), "托管.组合规则")
        minimum_activities = _positive_int(
            combination.get("最少活动数"), "托管.组合规则.最少活动数"
        )
        maximum_activities = _positive_int(
            combination.get("最多活动数"), "托管.组合规则.最多活动数"
        )
        if combination.get("允许重复") is not True:
            raise JsonDataError("托管组合必须允许活动重复")
        if minimum_activities > maximum_activities:
            raise JsonDataError("托管组合最少活动数不能大于最多活动数")
        if maximum_seconds % activity_seconds:
            raise JsonDataError("单次托管最长时间必须是活动时长的整数倍")

        if set(control_states) != {"自主", "托管中"}:
            raise JsonDataError("托管.控制状态必须完整包含自主和托管中")
        if set(mode_names) != {"personal", "team", "sect"}:
            raise JsonDataError("托管.同行类型必须完整包含personal、team、sect")
        if set(role_names) != {"personal", "leader", "follower"}:
            raise JsonDataError("托管.托管身份定义不完整")
        if context_fields != {
            "托管编号",
            "托管身份",
            "托管领队",
            "同行类型",
            "同行编号",
        }:
            raise JsonDataError("托管.上下文字段定义不完整")

        activities = self._load_activities(rule.get("活动"))
        for name, state_id in control_states.items():
            state = self._data.entity("人物状态", state_id)
            if state.get("名称") != name:
                raise JsonDataError(f"托管控制状态与人物状态不一致：{name}")

        self._control_states = MappingProxyType(control_states)
        self._mode_names = MappingProxyType(mode_names)
        self._role_names = MappingProxyType(role_names)
        self._activities = MappingProxyType(activities)
        self._context_fields = context_fields
        self._activity_seconds = activity_seconds
        self._maximum_seconds = maximum_seconds
        self._minimum_activities = minimum_activities
        self._maximum_activities = maximum_activities
        self._initialized = True
        return self.status()

    def status(self) -> HostingServiceStatus:
        return HostingServiceStatus(
            self._initialized,
            self._control_states,
            tuple(self._activities),
            self._activity_seconds,
            self._maximum_seconds,
            self._maximum_activities,
        )

    def normalize_activities(self, values: Sequence[object]) -> tuple[str, ...]:
        self._require_initialized()
        result = tuple(str(value or "").strip() for value in values)
        if len(result) < self._minimum_activities:
            raise HostingError("too_few_activities")
        if len(result) > self._maximum_activities:
            raise HostingError("too_many_activities")
        if any(not value or value not in self._activities for value in result):
            raise HostingError("unknown_activity")
        return result

    async def start(
        self,
        user_id: str,
        request_id: str,
        activities: Sequence[object],
        *,
        now: datetime | None = None,
    ) -> HostingSession:
        self._require_initialized()
        normalized_user = _text(user_id, "user_id")
        normalized_request = _text(request_id, "request_id")
        sequence = self.normalize_activities(activities)
        committed = await self._database.committed_transaction(
            normalized_user, normalized_request
        )
        if committed is not None:
            if committed.receipt.business_type != "托管:启动":
                raise HostingError("request_conflict")
            return _session_from_payload(committed.payload)

        try:
            group = await self._action_group.resolve(normalized_user)
        except ActionGroupError as exc:
            raise HostingError(exc.code) from exc
        if group.mode != "personal" and group.leader_user_id != normalized_user:
            raise HostingError("member_cannot_start")
        snapshots = await self._player_state.current_many(group.participant_user_ids)
        if len(snapshots) != len(group.participant_user_ids):
            raise HostingError("state_incomplete")
        for snapshot in snapshots:
            guard = await self._player_state.authorize(snapshot.user_id, "可开启托管")
            if not guard.allowed:
                raise HostingError(
                    "already_hosting"
                    if snapshot.states[CONTROL_TYPE].state_id
                    == self._control_states["托管中"]
                    else "participant_busy"
                )

        started_at = _utc(now)
        digest = hashlib.sha256(
            f"{normalized_user}\0{normalized_request}".encode()
        ).hexdigest()[:24]
        session_id = f"host-{digest}"
        value = {
            "名称": session_id,
            "托管编号": session_id,
            "发起用户": normalized_user,
            "托管领队": group.leader_user_id,
            "参与用户": list(group.participant_user_ids),
            "同行类型": group.mode,
            "同行编号": group.group_id,
            "活动顺序": list(sequence),
            "当前序号": 0,
            "当前阶段": WAIT_START,
            "下次触发时间": started_at.isoformat(),
            "开始时间": started_at.isoformat(),
            "到期时间": (
                started_at + timedelta(seconds=self._maximum_seconds)
            ).isoformat(),
            "完成循环": 0,
            "执行次数": 0,
            "运行状态": RUNNING,
            "当前命令": None,
            "当前请求": None,
            "最近错误": None,
            "最近提示": "首项活动将在片刻后自动开始。",
        }
        operations = [
            SharedEntityMutation(PLAN_ENTITY_TYPE, session_id, value, 0),
        ]
        for snapshot in snapshots:
            operations.append(
                (
                    await self._player_state.plan_transition(
                        StateTransitionCommand(
                            snapshot.user_id,
                            "托管计划",
                            CONTROL_TYPE,
                            self._control_states["托管中"],
                            self._control_context(group, snapshot.user_id, session_id),
                            expected_version=snapshot.version,
                        )
                    )
                ).mutation
            )
        await self._database.commit(
            TransactionCommand(
                user_id=normalized_user,
                request_id=normalized_request,
                business_type="托管:启动",
                operations=tuple(operations),
                payload={"计划": value},
            )
        )
        return _session_from_value(value)

    async def current(self, user_id: str) -> HostingSession | None:
        self._require_initialized()
        normalized = _text(user_id, "user_id")
        snapshot = await self._player_state.current(normalized)
        if (
            snapshot is None
            or snapshot.states[CONTROL_TYPE].state_id != self._control_states["托管中"]
        ):
            return None
        session_id = str(
            snapshot.states[CONTROL_TYPE].context.get("托管编号") or ""
        ).strip()
        if not session_id:
            raise HostingError("session_invalid")
        record = await self._database.get_shared_entity(PLAN_ENTITY_TYPE, session_id)
        if record is None:
            raise HostingError("session_invalid")
        session = _session_from_value(record.value)
        if normalized not in session.participant_user_ids:
            raise HostingError("session_invalid")
        return session

    async def latest(self, user_id: str) -> HostingSession | None:
        self._require_initialized()
        snapshot = await self._database.get(
            StateAddress(_text(user_id, "user_id"), LATEST_STATE, LATEST_KEY)
        )
        return _session_from_value(snapshot.value) if snapshot is not None else None

    async def cancel(self, user_id: str, request_id: str) -> HostingSession:
        self._require_initialized()
        normalized_user = _text(user_id, "user_id")
        normalized_request = _text(request_id, "request_id")
        # 取消可能与本地驱动器认领/完成同一时间发生。每次冲突都重新读取
        # 计划和参与者状态，最多短重试三次；不持有进程锁，避免阻塞其他玩家。
        for attempt in range(3):
            committed = await self._database.committed_transaction(
                normalized_user, normalized_request
            )
            if committed is not None:
                if committed.receipt.business_type != "托管:取消":
                    raise HostingError("request_conflict")
                return _session_from_payload(committed.payload)
            session = await self.current(normalized_user)
            if session is None:
                raise HostingError("not_hosting")
            if normalized_user != session.leader_user_id:
                raise HostingError("member_cannot_cancel")
            record = await self._database.get_shared_entity(
                PLAN_ENTITY_TYPE, session.session_id
            )
            if record is None:
                raise HostingError("session_invalid")
            finished = materialize(record.value)
            finished.update(
                {
                    "运行状态": "已取消",
                    "下次触发时间": None,
                    "当前命令": None,
                    "当前请求": None,
                    "最近错误": None,
                    "最近提示": "托管已经取消；如有活动已经开始，仍需手动查看或结束。",
                }
            )
            operations = await self._release_operations(session)
            operations.extend(await self._latest_operations(session, finished))
            operations.append(
                SharedEntityMutation(
                    PLAN_ENTITY_TYPE, session.session_id, None, record.version
                )
            )
            try:
                await self._database.commit(
                    TransactionCommand(
                        user_id=normalized_user,
                        request_id=normalized_request,
                        business_type="托管:取消",
                        operations=tuple(operations),
                        payload={"计划": finished},
                    )
                )
            except StateConflictError:
                if attempt < 2:
                    await asyncio.sleep(0)
                    continue
                raise HostingError("cancel_conflict") from None
            return _session_from_value(finished)
        raise HostingError("cancel_conflict")

    async def resume(
        self, user_id: str, request_id: str, *, now: datetime | None = None
    ) -> HostingSession:
        self._require_initialized()
        normalized_user = _text(user_id, "user_id")
        normalized_request = _text(request_id, "request_id")
        committed = await self._database.committed_transaction(
            normalized_user, normalized_request
        )
        if committed is not None:
            if committed.receipt.business_type != "托管:恢复":
                raise HostingError("request_conflict")
            return _session_from_payload(committed.payload)
        session = await self.current(normalized_user)
        if session is None:
            raise HostingError("not_hosting")
        if normalized_user != session.leader_user_id:
            raise HostingError("member_cannot_resume")
        if session.status != PAUSED:
            raise HostingError("not_paused")
        await self._validate_action_group(session)
        record = await self._database.get_shared_entity(
            PLAN_ENTITY_TYPE, session.session_id
        )
        if record is None:
            raise HostingError("session_invalid")
        value = materialize(record.value)
        value.update(
            {
                "运行状态": RUNNING,
                "下次触发时间": _utc(now).isoformat(),
                "最近错误": None,
                "最近提示": f"托管已经恢复，将继续{session.current_activity}。",
            }
        )
        await self._database.commit(
            TransactionCommand(
                normalized_user,
                normalized_request,
                "托管:恢复",
                (
                    SharedEntityMutation(
                        PLAN_ENTITY_TYPE, session.session_id, value, record.version
                    ),
                ),
                {"计划": value},
            )
        )
        return _session_from_value(value)

    async def active_plans(self) -> tuple[HostingSession, ...]:
        self._require_initialized()
        return tuple(
            session
            for record in await self._database.list_shared_entities(PLAN_ENTITY_TYPE)
            if (session := _session_from_value(record.value)).status == RUNNING
        )

    async def claim_execution(
        self, session_id: str, *, now: datetime | None = None
    ) -> HostingExecution | None:
        self._require_initialized()
        record = await self._database.get_shared_entity(
            PLAN_ENTITY_TYPE, _text(session_id, "托管编号")
        )
        if record is None:
            return None
        session = _session_from_value(record.value)
        if session.status != RUNNING:
            return None
        current = _utc(now)
        if session.phase in {EXECUTE_START, EXECUTE_END}:
            return self._execution_from_value(record.value, current)
        if session.next_trigger_at is None or session.next_trigger_at > current:
            return None
        try:
            await self._validate_action_group(session)
        except HostingError as exc:
            await self._pause_record(record, session, exc.code)
            return None
        if (
            session.phase == WAIT_START
            and session.expires_at is not None
            and current >= session.expires_at
        ):
            await self._finish_plan(record, session, "托管已达到24小时上限。")
            return None

        activity = self._activities[session.current_activity]
        execution_phase = EXECUTE_START if session.phase == WAIT_START else EXECUTE_END
        command = (
            activity.start_command
            if execution_phase == EXECUTE_START
            else activity.end_command
        )
        count = session.execution_count + 1
        request_id = f"{session.session_id}-{count:06d}-{execution_phase}"
        value = materialize(record.value)
        value.update(
            {
                "当前阶段": execution_phase,
                "执行次数": count,
                "当前命令": command,
                "当前请求": request_id,
                "下次触发时间": current.isoformat(),
                "最近错误": None,
                "最近提示": f"正在自动执行“{command}”。",
            }
        )
        try:
            await self._database.commit(
                TransactionCommand(
                    session.leader_user_id,
                    f"claim-{request_id}",
                    "托管:认领步骤",
                    (
                        SharedEntityMutation(
                            PLAN_ENTITY_TYPE,
                            session.session_id,
                            value,
                            record.version,
                        ),
                    ),
                    {"托管编号": session.session_id, "当前请求": request_id},
                )
            )
        except StateConflictError:
            return None
        return HostingExecution(
            session.session_id,
            session.leader_user_id,
            session.participant_user_ids,
            session.current_activity,
            execution_phase,
            command,
            request_id,
            current,
        )

    async def authorize_execution(
        self,
        *,
        user_id: str,
        request_id: str,
        activity: str,
        phase: str,
    ) -> bool:
        if not self._initialized or phase not in {"start", "end"}:
            return False
        snapshot = await self._player_state.current(str(user_id or "").strip())
        if (
            snapshot is None
            or snapshot.states[CONTROL_TYPE].state_id != self._control_states["托管中"]
        ):
            return False
        session_id = str(
            snapshot.states[CONTROL_TYPE].context.get("托管编号") or ""
        ).strip()
        record = await self._database.get_shared_entity(PLAN_ENTITY_TYPE, session_id)
        if record is None:
            return False
        session = _session_from_value(record.value)
        expected_phase = EXECUTE_START if phase == "start" else EXECUTE_END
        return bool(
            session.status == RUNNING
            and session.leader_user_id == user_id
            and session.current_activity == activity
            and session.phase == expected_phase
            and str(record.value.get("当前请求") or "") == request_id
        )

    async def verify_execution(self, execution: HostingExecution) -> bool:
        activity = self._activities.get(execution.activity)
        if activity is None:
            return False
        snapshots = await self._player_state.current_many(
            execution.participant_user_ids
        )
        if len(snapshots) != len(execution.participant_user_ids):
            return False
        expected = (
            activity.state_id
            if execution.phase == EXECUTE_START
            else activity.end_state_id
        )
        return all(
            snapshot.states["行为"].state_id == expected for snapshot in snapshots
        )

    async def complete_execution(
        self,
        execution: HostingExecution,
        *,
        success: bool,
        error: str = "",
        now: datetime | None = None,
    ) -> HostingSession | None:
        self._require_initialized()
        record = await self._database.get_shared_entity(
            PLAN_ENTITY_TYPE, execution.session_id
        )
        if record is None:
            return None
        session = _session_from_value(record.value)
        if str(record.value.get("当前请求") or "") != execution.request_id:
            return session
        if not success:
            return await self._pause_record(
                record,
                session,
                _clean_error(error) or f"“{execution.command}”没有完成。",
            )

        current = _utc(now)
        value = materialize(record.value)
        value["当前命令"] = None
        value["当前请求"] = None
        value["最近错误"] = None
        if execution.phase == EXECUTE_START:
            value.update(
                {
                    "当前阶段": WAIT_END,
                    "下次触发时间": (
                        current + timedelta(seconds=self._activity_seconds)
                    ).isoformat(),
                    "最近提示": (
                        f"{execution.activity}已经开始，将在30分钟后执行“"
                        f"{self._activities[execution.activity].end_command}”。"
                    ),
                }
            )
        else:
            next_index = (session.current_index + 1) % len(session.activities)
            cycle_count = session.cycle_count + int(next_index == 0)
            if session.expires_at is not None and current >= session.expires_at:
                return await self._finish_plan(
                    record,
                    session,
                    f"{execution.activity}已经完成，本次托管达到24小时上限。",
                    request_id=f"complete-{execution.request_id}",
                )
            value.update(
                {
                    "当前序号": next_index,
                    "当前阶段": WAIT_START,
                    "下次触发时间": current.isoformat(),
                    "完成循环": cycle_count,
                    "最近提示": (
                        f"{execution.activity}已经完成，下一项为"
                        f"{session.activities[next_index]}。"
                    ),
                }
            )
        try:
            await self._database.commit(
                TransactionCommand(
                    session.leader_user_id,
                    f"complete-{execution.request_id}",
                    "托管:完成步骤",
                    (
                        SharedEntityMutation(
                            PLAN_ENTITY_TYPE,
                            session.session_id,
                            value,
                            record.version,
                        ),
                    ),
                    {"计划": value},
                )
            )
        except StateConflictError:
            latest = await self._database.get_shared_entity(
                PLAN_ENTITY_TYPE, session.session_id
            )
            return _session_from_value(latest.value) if latest is not None else None
        return _session_from_value(value)

    def _load_activities(self, raw: object) -> dict[str, HostingActivity]:
        definitions = _mapping(raw, "托管.活动")
        result: dict[str, HostingActivity] = {}
        commands: set[str] = set()
        for raw_name, raw_definition in definitions.items():
            name = _text(raw_name, "托管.活动名称")
            definition = _mapping(raw_definition, f"托管.活动.{name}")
            state_id = _text(definition.get("行为状态"), f"托管.活动.{name}.行为状态")
            state = self._data.entity("人物状态", state_id)
            if self._player_state.state_type(state_id) != "行为":
                raise JsonDataError(f"托管活动{name}没有引用行为状态")
            end_state_id = _text(state.get("结束后"), f"托管.活动.{name}.结束后")
            start_command = _text(
                definition.get("开始命令"), f"托管.活动.{name}.开始命令"
            )
            end_command = _text(
                definition.get("结束命令"), f"托管.活动.{name}.结束命令"
            )
            if start_command in commands or end_command in commands:
                raise JsonDataError("不同托管活动不能复用开始或结束命令")
            commands.update((start_command, end_command))
            result[name] = HostingActivity(
                name, state_id, end_state_id, start_command, end_command
            )
        if not result:
            raise JsonDataError("托管必须至少定义一个活动")
        return result

    def _control_context(
        self, group, user_id: str, session_id: str
    ) -> dict[str, object]:
        role = (
            self._role_names["personal"]
            if group.mode == "personal"
            else self._role_names[
                "leader" if user_id == group.leader_user_id else "follower"
            ]
        )
        return {
            "托管编号": session_id,
            "托管身份": role,
            "托管领队": group.leader_user_id if group.mode != "personal" else None,
            "同行类型": self._mode_names[group.mode],
            "同行编号": group.group_id or None,
        }

    async def _validate_action_group(self, session: HostingSession) -> None:
        try:
            group = await self._action_group.group_for_user(session.leader_user_id)
        except ActionGroupError as exc:
            raise HostingError(exc.code) from exc
        if (
            group.mode != session.mode
            or group.leader_user_id != session.leader_user_id
            or group.participant_user_ids != session.participant_user_ids
        ):
            raise HostingError("group_changed")

    async def _release_operations(self, session: HostingSession) -> list:
        snapshots = await self._player_state.current_many(session.participant_user_ids)
        if len(snapshots) != len(session.participant_user_ids):
            raise HostingError("state_incomplete")
        operations = []
        for snapshot in snapshots:
            control = snapshot.states[CONTROL_TYPE]
            if control.state_id == self._control_states["自主"]:
                continue
            if (
                control.state_id != self._control_states["托管中"]
                or control.context.get("托管编号") != session.session_id
            ):
                raise HostingError("session_invalid")
            operations.append(
                (
                    await self._player_state.plan_transition(
                        StateTransitionCommand(
                            snapshot.user_id,
                            "托管计划",
                            CONTROL_TYPE,
                            self._control_states["自主"],
                            {},
                            expected_version=snapshot.version,
                        )
                    )
                ).mutation
            )
        return operations

    async def _latest_operations(
        self, session: HostingSession, value: Mapping[str, object]
    ) -> list[StateMutation]:
        operations = []
        for user_id in session.participant_user_ids:
            previous = await self._database.get(
                StateAddress(user_id, LATEST_STATE, LATEST_KEY)
            )
            operations.append(
                StateMutation(
                    user_id,
                    LATEST_STATE,
                    LATEST_KEY,
                    materialize(value),
                    previous.version if previous is not None else 0,
                )
            )
        return operations

    async def _pause_record(
        self,
        record,
        session: HostingSession,
        error: str,
    ) -> HostingSession:
        value = materialize(record.value)
        phase = value.get("当前阶段")
        if phase == EXECUTE_START:
            value["当前阶段"] = WAIT_START
        elif phase == EXECUTE_END:
            value["当前阶段"] = WAIT_END
        value.update(
            {
                "运行状态": PAUSED,
                "下次触发时间": None,
                "当前命令": None,
                "当前请求": None,
                "最近错误": error,
                "最近提示": f"托管已经暂停：{error}",
            }
        )
        try:
            await self._database.commit(
                TransactionCommand(
                    session.leader_user_id,
                    f"pause-{session.session_id}-{session.execution_count:06d}",
                    "托管:暂停",
                    (
                        SharedEntityMutation(
                            PLAN_ENTITY_TYPE,
                            session.session_id,
                            value,
                            record.version,
                        ),
                    ),
                    {"计划": value},
                )
            )
        except StateConflictError:
            latest = await self._database.get_shared_entity(
                PLAN_ENTITY_TYPE, session.session_id
            )
            if latest is not None:
                return _session_from_value(latest.value)
        return _session_from_value(value)

    async def _finish_plan(
        self,
        record,
        session: HostingSession,
        message: str,
        *,
        request_id: str | None = None,
    ) -> HostingSession:
        finished = materialize(record.value)
        finished.update(
            {
                "运行状态": "已到期",
                "下次触发时间": None,
                "当前命令": None,
                "当前请求": None,
                "最近错误": None,
                "最近提示": message,
            }
        )
        operations = await self._release_operations(session)
        operations.extend(await self._latest_operations(session, finished))
        operations.append(
            SharedEntityMutation(
                PLAN_ENTITY_TYPE, session.session_id, None, record.version
            )
        )
        await self._database.commit(
            TransactionCommand(
                session.leader_user_id,
                request_id or f"expire-{session.session_id}",
                "托管:到期",
                tuple(operations),
                {"计划": finished, "提示": message},
            )
        )
        return _session_from_value(finished)

    def _execution_from_value(
        self, value: Mapping[str, object], current: datetime
    ) -> HostingExecution:
        session = _session_from_value(value)
        command = _text(value.get("当前命令"), "托管计划.当前命令")
        request_id = _text(value.get("当前请求"), "托管计划.当前请求")
        return HostingExecution(
            session.session_id,
            session.leader_user_id,
            session.participant_user_ids,
            session.current_activity,
            session.phase,
            command,
            request_id,
            current,
        )

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("托管核心微服务尚未初始化")


def _session_from_payload(payload: Mapping[str, object]) -> HostingSession:
    raw = payload.get("计划", payload)
    return _session_from_value(_mapping(raw, "托管事务.计划"))


def _session_from_value(value: Mapping[str, object]) -> HostingSession:
    activities = _strings(value.get("活动顺序"), "托管计划.活动顺序")
    current_index = _nonnegative_int(value.get("当前序号"), "托管计划.当前序号")
    if current_index >= len(activities):
        raise HostingError("transaction_invalid")
    phase = _text(value.get("当前阶段"), "托管计划.当前阶段")
    if phase not in PHASES:
        raise HostingError("transaction_invalid")
    status = _text(value.get("运行状态"), "托管计划.运行状态")
    if status not in {RUNNING, PAUSED, "已取消", "已到期"}:
        raise HostingError("transaction_invalid")
    raw_next = value.get("下次触发时间")
    next_trigger_at = (
        _parse_time(raw_next, "托管计划.下次触发时间") if raw_next else None
    )
    return HostingSession(
        _text(value.get("托管编号"), "托管计划.托管编号"),
        _mode(value.get("同行类型")),
        _text(value.get("托管领队"), "托管计划.托管领队"),
        _strings(value.get("参与用户"), "托管计划.参与用户"),
        activities,
        current_index,
        phase,
        next_trigger_at,
        _parse_time(value.get("到期时间"), "托管计划.到期时间"),
        _nonnegative_int(value.get("完成循环"), "托管计划.完成循环"),
        _nonnegative_int(value.get("执行次数"), "托管计划.执行次数"),
        status,
        str(value.get("最近错误") or "").strip(),
        str(value.get("最近提示") or "").strip(),
    )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return value


def _string_mapping(value: object, label: str) -> dict[str, str]:
    raw = _mapping(value, label)
    result = {str(key): str(item or "").strip() for key, item in raw.items()}
    if any(not key or not item for key, item in result.items()):
        raise JsonDataError(f"{label}不能包含空键或空值")
    return result


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError(f"{label}必须是字符串数组")
    result = tuple(str(item or "").strip() for item in value)
    if not result or any(not item for item in result):
        raise JsonDataError(f"{label}不能包含空值")
    return result


def _text(value: object, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise JsonDataError(f"{label}不能为空")
    return result


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise JsonDataError(f"{label}必须是正整数")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise JsonDataError(f"{label}必须是非负整数")
    return value


def _mode(value: object) -> str:
    result = _text(value, "托管计划.同行类型")
    if result not in {"personal", "team", "sect"}:
        raise HostingError("transaction_invalid")
    return result


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("托管时间必须包含时区")
    return current.astimezone(timezone.utc)


def _parse_time(value: object, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value, label))
    except ValueError as exc:
        raise HostingError("transaction_invalid") from exc
    if parsed.tzinfo is None:
        raise HostingError("transaction_invalid")
    return parsed.astimezone(timezone.utc)


def _clean_error(value: object) -> str:
    return " ".join(str(value or "").split())[:240]


__all__ = ["HostingService"]
