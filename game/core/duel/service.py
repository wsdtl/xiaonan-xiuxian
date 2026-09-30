from __future__ import annotations

from collections.abc import Sequence, Mapping
from game.core.database import (
    DatabaseMutation,
    DatabaseService,
    StateAddress,
    StateConflictError,
    StateMutation,
    TransactionCommand,
)

from game.core.combat import (
    CombatantSpec,
    CombatGroupSpec,
    CombatReportSpec,
    CombatRequest,
    CombatService,
)

import asyncio
import hashlib
import json
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from launch.battle_log import BattleReportSink

from game.core.action_group import ActionGroupError, ActionGroupService
from game.core.character import CharacterService
from game.core.companion import CompanionService
from game.core.data import JsonDataError, JsonDataService, materialize, nonempty_text, positive_int
from game.core.location import LocationService
from game.core.player_state import PlayerStateService

from .contracts import DuelChallenge, DuelError, DuelResult, DuelStartCommand

CHALLENGE_STATE = "duel_challenge"


class DuelService:
    state_types = frozenset({CHALLENGE_STATE})

    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService,
        location: LocationService,
        character: CharacterService,
        companion: CompanionService,
        player_state: PlayerStateService,
        action_group: ActionGroupService,
        combat: CombatService,
        battle_reports: BattleReportSink | None = None,
    ) -> None:
        self._data = data
        self._database = database
        self._location = location
        self._character = character
        self._companion = companion
        self._player_state = player_state
        self._action_group = action_group
        self._combat = combat
        self._battle_reports = battle_reports
        self._initialized = False
        self._rules: Mapping[str, object] = {}

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("切磋核心已经初始化")
        rules = self._data.dataset("玩法规则").get("切磋")
        if not isinstance(rules, Mapping):
            raise JsonDataError("玩法/切磋/规则/切磋.json 必须是对象")
        self._rules = dict(rules)
        _positive_int(self._rules.get("有效秒数"), "切磋.有效秒数")
        _positive_int(self._rules.get("战斗行动上限"), "切磋.战斗行动上限")
        self._initialized = True

    async def resolve_target(self, user_id: str, query: str) -> str:
        candidates = await self._location.nearby_players(user_id)
        available = tuple(value.user_id for value in candidates.values)
        query = _text(query, "切磋目标")
        if query in available:
            return query
        profiles = await self._character.public_profiles(available)
        matches = tuple(value.user_id for value in profiles if value.name == query)
        if not matches:
            raise DuelError("目标不在附近")
        if len(matches) > 1:
            raise DuelError("目标姓名重名，请改用用户编号")
        return matches[0]

    async def start(self, command: DuelStartCommand) -> DuelChallenge:
        self._require_initialized()
        user_id = _text(command.user_id, "发起者")
        target = _text(command.target_user_id, "目标")
        request_id = _text(command.request_id, "请求编号")
        if user_id == target:
            raise DuelError("不能与自己切磋")
        participants = await self._action_participants(user_id)
        target_participants = await self._target_participants(target)
        await self._validate_participants((*participants, *target_participants))
        if set(participants) & set(target_participants):
            raise DuelError("切磋双方不能包含同一玩家")
        challenge_id = _challenge_id(user_id, target, request_id)
        existing = await self._database.get(
            StateAddress(target, CHALLENGE_STATE, "main")
        )
        if existing is not None and not _expired(existing.value):
            if str(existing.value.get("切磋编号")) == challenge_id:
                return _challenge(existing.value, replayed=True)
            raise DuelError("目标已有待处理的切磋")
        now = _utc(command.created_at or datetime.now(UTC))
        expires_at = now + timedelta(seconds=_positive_int(self._rules["有效秒数"], "切磋.有效秒数"))
        value = {
            "切磋编号": challenge_id,
            "发起者": user_id,
            "目标": target,
            "发起方": list(participants),
            "目标方": list(target_participants),
            "创建时间": now.isoformat(),
            "过期时间": expires_at.isoformat(),
        }
        await self._commit(
            user_id,
            request_id,
            "发起切磋",
            (StateMutation(target, CHALLENGE_STATE, "main", value, existing.version if existing else 0),),
        )
        return DuelChallenge(challenge_id, user_id, target, participants, target_participants, expires_at, False)

    async def accept(self, user_id: str, request_id: str) -> DuelResult:
        self._require_initialized()
        target = _text(user_id, "接受者")
        request = _text(request_id, "请求编号")
        pending = await self._database.get(StateAddress(target, CHALLENGE_STATE, "main"))
        if pending is None or _expired(pending.value):
            raise DuelError("没有待处理的切磋")
        value = pending.value
        challenge_id = _text(value.get("切磋编号"), "切磋编号")
        owner = _text(value.get("发起者"), "发起者")
        if self._battle_reports is None:
            raise RuntimeError("切磋核心缺少非资产战报库")
        replayed = self._battle_reports.load(challenge_id)
        if replayed is not None:
            return _result(json.loads(str(getattr(replayed, "report_json", "") or "{}")), replayed=True)
        users = tuple(_texts(value.get("发起方"), "发起方") + _texts(value.get("目标方"), "目标方"))
        current_left = await self._action_participants(owner)
        current_right = await self._action_participants(target)
        if current_left != tuple(_texts(value.get("发起方"), "发起方")) or current_right != tuple(_texts(value.get("目标方"), "目标方")):
            raise DuelError("队伍或宗门同行名单已经变化，请重新发起切磋")
        await self._validate_participants(users)
        combatants, groups = await self._combat_side(current_left, challenge_id, "甲方")
        right_combatants, right_groups = await self._combat_side(current_right, challenge_id, "乙方")
        result = await self._combat.execute(
            CombatRequest(
                left_team=tuple(combatants),
                right_team=tuple(right_combatants),
                seed=_seed(challenge_id),
                action_limit=_positive_int(self._rules["战斗行动上限"], "切磋.战斗行动上限"),
                report=CombatReportSpec(scene="切磋"),
                left_groups=groups,
                right_groups=right_groups,
            )
        )
        stored = {
            "切磋编号": challenge_id,
            "发起者": owner,
            "目标": target,
            "发起方": list(current_left),
            "目标方": list(current_right),
            "胜方": result.winner_side or "平局",
            "行动数": result.actions,
            "事件数": len(result.events),
            "战报": materialize(result.report or {}),
            "完成时间": datetime.now(UTC).isoformat(),
        }
        await self._commit(
            target,
            request,
            "接受切磋",
            (StateMutation(target, CHALLENGE_STATE, "main", None, pending.version),),
        )
        # 战报是**非资产数据**：只登记进非资产库（按编号分享、到期即清理），不进玩家状态。
        self._battle_reports.save(
            report_id=challenge_id,
            kind="切磋",
            participants=(owner, target),
            finished_at=_text(stored["完成时间"], "完成时间"),
            finished_timestamp=time.time(),
            report_json=json.dumps(stored, ensure_ascii=False),
        )
        return _result(stored, replayed=False)

    async def reject(self, user_id: str, request_id: str) -> None:
        pending = await self._database.get(StateAddress(_text(user_id, "拒绝者"), CHALLENGE_STATE, "main"))
        if pending is None:
            raise DuelError("没有待处理的切磋")
        await self._commit(user_id, request_id, "拒绝切磋", (StateMutation(user_id, CHALLENGE_STATE, "main", None, pending.version),))

    async def _action_participants(self, user_id: str) -> tuple[str, ...]:
        try:
            return (await self._action_group.resolve(user_id)).participant_user_ids
        except ActionGroupError as exc:
            if exc.code == "member_cannot_start":
                raise DuelError("只有队长或宗主可以代表同行编组发起切磋") from exc
            if exc.code == "fellowship_conflict":
                raise DuelError("队伍同行与宗门同行不能同时存在") from exc
            raise DuelError(str(exc)) from exc

    async def _target_participants(self, user_id: str) -> tuple[str, ...]:
        try:
            group = await self._action_group.group_for_user(user_id)
        except ActionGroupError as exc:
            raise DuelError(str(exc)) from exc
        if group.leader_user_id != user_id:
            raise DuelError("切磋目标是同行成员，请改为挑战队长或宗主")
        return group.participant_user_ids

    async def _validate_participants(self, users: tuple[str, ...]) -> None:
        if len(users) > 15 or len(set(users)) != len(users):
            raise DuelError("切磋参战玩家数量或名单无效")
        locations = await asyncio.gather(*(self._location.current(user) for user in users))
        if len({(v.space_type, v.space_id, v.xy) for v in locations}) != 1:
            raise DuelError("切磋双方必须处于同一位置")
        profiles = {
            value.user_id: value
            for value in await self._character.public_profiles(users)
        }
        for user_id in users:
            guard = await self._player_state.authorize(
                user_id, "自主空闲或休息且可行动"
            )
            if not guard.allowed:
                profile = profiles.get(user_id)
                raise DuelError(
                    f"{profile.name if profile else '有同行修士'}当前不能切磋：{guard.reason}"
                )

    async def _combat_side(self, users: tuple[str, ...], challenge_id: str, side: str) -> tuple[tuple[CombatantSpec, ...], tuple[CombatGroupSpec, ...]]:
        combatants = []
        groups = []
        for index, user_id in enumerate(users, start=1):
            group_id = f"切磋:{challenge_id}:{side}:{index:02d}"
            player = replace(await self._character.combatant(user_id), group_id=group_id, group_role="主战者")
            members = [player.id]
            combatants.append(player)
            companion = await self._companion.combatant(user_id)
            if companion is not None:
                companion = replace(companion, group_id=group_id, group_role="主战者")
                combatants.append(companion)
                members.append(companion.id)
            groups.append(CombatGroupSpec(group_id, tuple(members), tuple(members)))
        return tuple(combatants), tuple(groups)

    async def _commit(self, user_id: str, request_id: str, business_type: str, operations: Sequence[DatabaseMutation]) -> None:
        try:
            await self._database.commit(TransactionCommand(user_id, request_id, business_type, tuple(operations), {}))
        except StateConflictError as exc:
            raise DuelError("切磋状态已经变化，请重试") from exc

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("切磋核心尚未初始化")


def _challenge_id(user_id: str, target: str, request_id: str) -> str:
    return hashlib.sha256(f"{user_id}\0{target}\0{request_id}".encode()).hexdigest()[:24]


def _seed(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big")


def _challenge(value: Mapping[str, object], *, replayed: bool) -> DuelChallenge:
    return DuelChallenge(_text(value.get("切磋编号"), "切磋编号"), _text(value.get("发起者"), "发起者"), _text(value.get("目标"), "目标"), tuple(_texts(value.get("发起方"), "发起方")), tuple(_texts(value.get("目标方"), "目标方")), _utc(value.get("过期时间")), replayed)


def _result(value: Mapping[str, object], *, replayed: bool) -> DuelResult:
    return DuelResult(_text(value.get("切磋编号"), "切磋编号"), _text(value.get("发起者"), "发起者"), _text(value.get("胜方"), "胜方"), tuple(_texts(value.get("发起方"), "发起方")), tuple(_texts(value.get("目标方"), "目标方")), int(value.get("行动数", 0)), int(value.get("事件数", 0)), replayed)


def _expired(value: Mapping[str, object]) -> bool:
    return _utc(value.get("过期时间")) <= datetime.now(UTC)


def _utc(value: object) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return (result if result.tzinfo else result.replace(tzinfo=UTC)).astimezone(UTC)


def _text(value: object, label: str) -> str:
    return nonempty_text(value, label, error=DuelError)


def _texts(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise DuelError(f"{label}不能为空")
    return tuple(_text(item, label) for item in value)


def _positive_int(value: object, label: str) -> int:
    return positive_int(value, label, error=DuelError)
