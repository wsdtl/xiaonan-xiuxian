"""由 JSON 驱动的玩家队伍聚合与邀请服务。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from uuid import NAMESPACE_URL, uuid5

from game.core.data import (
    JsonDataError,
    JsonDataService,
    mapping as _mapping,
    positive_int as _positive_int,
)
from game.core.database import (
    DatabaseService,
    StateAddress,
    StateConflictError,
    StateMutation,
    TransactionCommand,
)
from game.core.player_state import (
    PlayerStateConflictError,
    PlayerStateService,
    StateContextUpdateCommand,
    StateTransitionCommand,
)

from .contracts import (
    PublicTeamState,
    TeamConflictError,
    TeamInvitation,
    TeamMembership,
    TeamRuleError,
    TeamServiceStatus,
    TeamSnapshot,
)

TEAM_STATE = "team"
INVITATION_STATE = "team_invite"
MAIN_KEY = "main"


class TeamService:
    """拥有队伍聚合和队伍邀请写权限的唯一核心服务。"""

    state_types = frozenset({TEAM_STATE, INVITATION_STATE})

    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService,
        player_state: PlayerStateService,
    ) -> None:
        self._data = data
        self._database = database
        self._player_state = player_state
        self._initialized = False
        self._maximum_players = 0
        self._invitation_seconds = 0
        self._allow_single = False
        self._disband_single = False
        self._ungrouped_state_id = ""
        self._grouped_state_id = ""
        self._team_id_field = ""
        self._role_field = ""
        self._leader_role = ""
        self._member_role = ""
        self._public_grouped = False
        self._public_count = False

    def initialize(self) -> TeamServiceStatus:
        if self._initialized:
            raise RuntimeError("队伍核心微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据服务必须先于队伍核心启动")
        if not self._database.status().initialized:
            raise RuntimeError("核心数据库必须先于队伍核心启动")
        if not self._player_state.status().initialized:
            raise RuntimeError("人物状态核心必须先于队伍核心启动")
        root = _mapping(self._data.dataset("队伍规则").get("队伍"), "队伍.json")
        capacity = _mapping(root.get("人数"), "队伍.人数")
        invitation = _mapping(root.get("邀请"), "队伍.邀请")
        states = _mapping(root.get("玩家状态"), "队伍.玩家状态")
        roles = _mapping(root.get("身份"), "队伍.身份")
        public = _mapping(root.get("附近公开"), "队伍.附近公开")
        self._maximum_players = _positive_int(
            capacity.get("最多玩家"), "队伍.人数.最多玩家"
        )
        self._invitation_seconds = _positive_int(
            invitation.get("有效秒数"), "队伍.邀请.有效秒数"
        )
        self._allow_single = _boolean(
            capacity.get("允许单人队伍"), "队伍.人数.允许单人队伍"
        )
        self._disband_single = _boolean(
            capacity.get("只剩一人时解散"), "队伍.人数.只剩一人时解散"
        )
        self._ungrouped_state_id = _text(states.get("未组队"), "队伍.玩家状态.未组队")
        self._grouped_state_id = _text(states.get("组队中"), "队伍.玩家状态.组队中")
        self._team_id_field = _text(
            states.get("队伍编号字段"), "队伍.玩家状态.队伍编号字段"
        )
        self._role_field = _text(states.get("身份字段"), "队伍.玩家状态.身份字段")
        self._leader_role = _text(roles.get("队长"), "队伍.身份.队长")
        self._member_role = _text(roles.get("队员"), "队伍.身份.队员")
        self._public_grouped = _boolean(
            public.get("显示组队状态"), "队伍.附近公开.显示组队状态"
        )
        self._public_count = _boolean(
            public.get("显示玩家人数"), "队伍.附近公开.显示玩家人数"
        )
        if not self._allow_single:
            raise JsonDataError("当前队伍实现要求允许单人队伍")
        self._initialized = True
        return self.status()

    def status(self) -> TeamServiceStatus:
        return TeamServiceStatus(
            self._initialized,
            self._maximum_players,
            self._invitation_seconds,
        )

    async def membership(self, user_id: str) -> TeamMembership | None:
        self._require_initialized()
        user = _text(user_id, "user_id")
        state = await self._player_state.current(user)
        if state is None:
            raise TeamRuleError("character_missing")
        slot = state.states["队伍"]
        if slot.state_id == self._ungrouped_state_id:
            return None
        if slot.state_id != self._grouped_state_id:
            raise TeamRuleError("team_state_invalid")
        team_id = _text(slot.context.get(self._team_id_field), "队伍状态.队伍编号")
        role = _text(slot.context.get(self._role_field), "队伍状态.身份")
        team = await self._team(team_id)
        if team is None or user not in team.member_user_ids:
            raise TeamRuleError("team_state_incomplete")
        expected_role = (
            self._leader_role if team.leader_user_id == user else self._member_role
        )
        if role != expected_role:
            raise TeamRuleError("team_role_inconsistent")
        return TeamMembership(user, role, team)

    async def pending_invitation(
        self, user_id: str, *, now: datetime | None = None
    ) -> TeamInvitation | None:
        self._require_initialized()
        target = _text(user_id, "user_id")
        snapshot = await self._database.get(
            StateAddress(target, INVITATION_STATE, MAIN_KEY)
        )
        if snapshot is None:
            return None
        return _invitation(snapshot.value, snapshot.version, _utc(now))

    async def public_many(
        self, user_ids: tuple[str, ...]
    ) -> tuple[PublicTeamState, ...]:
        self._require_initialized()
        states = await self._player_state.current_many(user_ids)
        state_team_ids = {
            value.user_id: str(
                value.states["队伍"].context.get(self._team_id_field) or ""
            )
            for value in states
            if value.states["队伍"].state_id == self._grouped_state_id
        }
        team_ids = tuple(dict.fromkeys(state_team_ids.values()))
        teams = await self._database.get_many(
            tuple(StateAddress(team_id, TEAM_STATE, MAIN_KEY) for team_id in team_ids)
        )
        counts = {
            snapshot.address.user_id: len(
                _texts(snapshot.value.get("成员"), "队伍.成员")
            )
            for snapshot in teams
        }
        return tuple(
            PublicTeamState(
                state.user_id,
                bool(
                    (team_id := state_team_ids.get(state.user_id, ""))
                    and team_id in counts
                    and self._public_grouped
                ),
                counts.get(team_id, 0) if self._public_count else 0,
            )
            for state in states
        )

    async def action_participants(self, user_id: str) -> tuple[str, ...]:
        """返回行动玩家顺序；队员不能越过队长发起团队行动。"""

        membership = await self.membership(user_id)
        if membership is None:
            return (_text(user_id, "user_id"),)
        if membership.role != self._leader_role:
            raise TeamConflictError("member_cannot_start")
        return membership.team.member_user_ids

    async def invite(
        self,
        inviter_user_id: str,
        target_user_id: str,
        request_id: str,
        *,
        now: datetime | None = None,
    ) -> TeamInvitation:
        self._require_initialized()
        inviter = _text(inviter_user_id, "inviter_user_id")
        target = _text(target_user_id, "target_user_id")
        request = _text(request_id, "request_id")
        if inviter == target:
            raise TeamConflictError("cannot_invite_self")
        inviter_membership = await self.membership(inviter)
        target_membership = await self.membership(target)
        if target_membership is not None:
            raise TeamConflictError("target_grouped")
        operations: list[StateMutation] = []
        if inviter_membership is None:
            team_id = _team_id(inviter, request)
            team = TeamSnapshot(team_id, inviter, (inviter,), 0, "")
            operations.append(StateMutation(team_id, TEAM_STATE, MAIN_KEY, _team_value(team), 0))
            operations.append(
                (
                    await self._player_state.plan_transition(
                        StateTransitionCommand(
                            inviter,
                            request,
                            "队伍",
                            self._grouped_state_id,
                            self._context(team_id, self._leader_role),
                        )
                    )
                ).mutation
            )
        else:
            if inviter_membership.role != self._leader_role:
                raise TeamConflictError("not_leader")
            team = inviter_membership.team
            team_id = team.team_id
        if len(team.member_user_ids) >= self._maximum_players:
            raise TeamConflictError("team_full")
        current_time = _utc(now)
        previous = await self._database.get(
            StateAddress(target, INVITATION_STATE, MAIN_KEY)
        )
        if previous is not None:
            pending = _invitation(previous.value, previous.version, current_time)
            pending_team = await self._team(pending.team_id)
            if not pending.expired and pending_team is not None:
                raise TeamConflictError("pending_invitation_exists")
        expires_at = current_time + timedelta(seconds=self._invitation_seconds)
        invitation_value = {
            "邀请者": inviter,
            "目标": target,
            "队伍编号": team_id,
            "到期时间": expires_at.isoformat(),
        }
        operations.append(
            StateMutation(
                target,
                INVITATION_STATE,
                MAIN_KEY,
                invitation_value,
                previous.version if previous else 0,
            )
        )
        await self._commit(inviter, request, "队伍邀请", operations, {"目标": target})
        return TeamInvitation(
            inviter,
            target,
            team_id,
            expires_at,
            (previous.version if previous else 0) + 1,
            False,
        )

    async def accept(
        self, user_id: str, request_id: str, *, now: datetime | None = None
    ) -> TeamSnapshot:
        self._require_initialized()
        target = _text(user_id, "user_id")
        request = _text(request_id, "request_id")
        snapshot = await self._database.get(
            StateAddress(target, INVITATION_STATE, MAIN_KEY)
        )
        if snapshot is None:
            raise TeamConflictError("invitation_missing")
        invitation = _invitation(snapshot.value, snapshot.version, _utc(now))
        team = await self._team(invitation.team_id)
        if invitation.expired or team is None:
            await self._commit(
                target,
                request,
                "清理失效队伍邀请",
                (StateMutation(target, INVITATION_STATE, MAIN_KEY, None, snapshot.version),),
                {"队伍编号": invitation.team_id},
            )
            raise TeamConflictError("invitation_expired")
        if await self.membership(target) is not None:
            raise TeamConflictError("already_grouped")
        if team.leader_user_id != invitation.inviter_user_id:
            raise TeamConflictError("invitation_expired")
        if len(team.member_user_ids) >= self._maximum_players:
            raise TeamConflictError("team_full")
        members = team.member_user_ids + (target,)
        updated = TeamSnapshot(
            team.team_id,
            team.leader_user_id,
            members,
            team.version + 1,
            team.updated_at,
        )
        transition = await self._player_state.plan_transition(
            StateTransitionCommand(
                target,
                request,
                "队伍",
                self._grouped_state_id,
                self._context(team.team_id, self._member_role),
            )
        )
        await self._commit(
            target,
            request,
            "接受队伍邀请",
            (
                StateMutation(
                    team.team_id,
                    TEAM_STATE,
                    MAIN_KEY,
                    _team_value(updated),
                    team.version,
                ),
                transition.mutation,
                StateMutation(target, INVITATION_STATE, MAIN_KEY, None, snapshot.version),
            ),
            {"队伍编号": team.team_id, "邀请者": invitation.inviter_user_id},
        )
        return updated

    async def reject(self, user_id: str, request_id: str) -> str:
        self._require_initialized()
        target = _text(user_id, "user_id")
        snapshot = await self._database.get(
            StateAddress(target, INVITATION_STATE, MAIN_KEY)
        )
        if snapshot is None:
            raise TeamConflictError("invitation_missing")
        invitation = _invitation(snapshot.value, snapshot.version, _utc(None))
        await self._commit(
            target,
            _text(request_id, "request_id"),
            "拒绝队伍邀请",
            (StateMutation(target, INVITATION_STATE, MAIN_KEY, None, snapshot.version),),
            {"队伍编号": invitation.team_id},
        )
        return invitation.inviter_user_id

    async def leave(self, user_id: str, request_id: str) -> None:
        membership = await self._require_membership(user_id)
        await self._remove_member(
            membership,
            membership.user_id,
            _text(request_id, "request_id"),
            "离开队伍",
        )

    async def kick(self, user_id: str, target_user_id: str, request_id: str) -> None:
        membership = await self._require_leader(user_id)
        target = _text(target_user_id, "target_user_id")
        if target == membership.team.leader_user_id:
            raise TeamConflictError("cannot_remove_leader")
        if target not in membership.team.member_user_ids:
            raise TeamConflictError("target_not_member")
        await self._remove_member(
            membership,
            target,
            _text(request_id, "request_id"),
            "请离队伍成员",
        )

    async def transfer(
        self, user_id: str, target_user_id: str, request_id: str
    ) -> TeamSnapshot:
        membership = await self._require_leader(user_id)
        target = _text(target_user_id, "target_user_id")
        if target == membership.user_id:
            raise TeamConflictError("cannot_transfer_self")
        if target not in membership.team.member_user_ids:
            raise TeamConflictError("target_not_member")
        members = (target,) + tuple(
            value for value in membership.team.member_user_ids if value != target
        )
        updated = TeamSnapshot(
            membership.team.team_id,
            target,
            members,
            membership.team.version + 1,
            membership.team.updated_at,
        )
        old_plan = await self._player_state.plan_context_update(
            StateContextUpdateCommand(
                membership.user_id,
                "队伍",
                self._context(updated.team_id, self._member_role),
                self._grouped_state_id,
            )
        )
        new_plan = await self._player_state.plan_context_update(
            StateContextUpdateCommand(
                target,
                "队伍",
                self._context(updated.team_id, self._leader_role),
                self._grouped_state_id,
            )
        )
        await self._commit(
            membership.user_id,
            _text(request_id, "request_id"),
            "移交队长",
            (
                StateMutation(
                    updated.team_id,
                    TEAM_STATE,
                    MAIN_KEY,
                    _team_value(updated),
                    membership.team.version,
                ),
                old_plan.mutation,
                new_plan.mutation,
            ),
            {"新队长": target},
        )
        return updated

    async def disband(self, user_id: str, request_id: str) -> None:
        membership = await self._require_leader(user_id)
        operations: list[StateMutation] = [
            StateMutation(
                membership.team.team_id,
                TEAM_STATE,
                MAIN_KEY,
                None,
                membership.team.version,
            )
        ]
        for member in membership.team.member_user_ids:
            operations.append((await self._ungroup_plan(member, request_id)).mutation)
        await self._commit(
            membership.user_id,
            _text(request_id, "request_id"),
            "解散队伍",
            operations,
            {"队伍编号": membership.team.team_id},
        )

    async def _remove_member(
        self,
        actor: TeamMembership,
        target: str,
        request_id: str,
        business_type: str,
    ) -> None:
        team = actor.team
        remaining = tuple(value for value in team.member_user_ids if value != target)
        if len(remaining) == 1 and self._disband_single:
            operations: list[StateMutation] = [
                StateMutation(team.team_id, TEAM_STATE, MAIN_KEY, None, team.version)
            ]
            for member in team.member_user_ids:
                operations.append((await self._ungroup_plan(member, request_id)).mutation)
        elif not remaining:
            operations = [
                StateMutation(team.team_id, TEAM_STATE, MAIN_KEY, None, team.version),
                (await self._ungroup_plan(target, request_id)).mutation,
            ]
        else:
            leader = team.leader_user_id
            operations = []
            if target == leader:
                leader = remaining[0]
                leader_plan = await self._player_state.plan_context_update(
                    StateContextUpdateCommand(
                        leader,
                        "队伍",
                        self._context(team.team_id, self._leader_role),
                        self._grouped_state_id,
                    )
                )
                operations.append(leader_plan.mutation)
            updated = TeamSnapshot(
                team.team_id,
                leader,
                remaining,
                team.version + 1,
                team.updated_at,
            )
            operations.insert(
                0,
                StateMutation(
                    team.team_id,
                    TEAM_STATE,
                    MAIN_KEY,
                    _team_value(updated),
                    team.version,
                ),
            )
            operations.append((await self._ungroup_plan(target, request_id)).mutation)
        await self._commit(
            actor.user_id,
            request_id,
            business_type,
            operations,
            {"队伍编号": team.team_id, "目标": target},
        )

    async def _ungroup_plan(self, user_id: str, request_id: str):
        return await self._player_state.plan_transition(
            StateTransitionCommand(
                user_id,
                request_id,
                "队伍",
                self._ungrouped_state_id,
                {},
            )
        )

    async def _require_membership(self, user_id: str) -> TeamMembership:
        membership = await self.membership(user_id)
        if membership is None:
            raise TeamConflictError("not_grouped")
        return membership

    async def _require_leader(self, user_id: str) -> TeamMembership:
        membership = await self._require_membership(user_id)
        if membership.role != self._leader_role:
            raise TeamConflictError("not_leader")
        return membership

    async def _team(self, team_id: str) -> TeamSnapshot | None:
        snapshot = await self._database.get(StateAddress(team_id, TEAM_STATE, MAIN_KEY))
        if snapshot is None:
            return None
        members = _texts(snapshot.value.get("成员"), "队伍.成员")
        leader = _text(snapshot.value.get("队长"), "队伍.队长")
        if not members or members[0] != leader or len(members) != len(set(members)):
            raise TeamRuleError("team_snapshot_invalid")
        if len(members) > self._maximum_players:
            raise TeamRuleError("team_snapshot_overflow")
        return TeamSnapshot(
            team_id,
            leader,
            members,
            snapshot.version,
            snapshot.updated_at,
        )

    async def _commit(
        self,
        user_id: str,
        request_id: str,
        business_type: str,
        operations: Sequence[StateMutation],
        payload: Mapping[str, object],
    ) -> None:
        try:
            await self._database.commit(
                TransactionCommand(
                    user_id=user_id,
                    request_id=request_id,
                    business_type=business_type,
                    operations=tuple(operations),
                    payload=MappingProxyType(dict(payload)),
                )
            )
        except (StateConflictError, PlayerStateConflictError) as exc:
            raise TeamConflictError("team_changed") from exc

    def _context(self, team_id: str, role: str) -> dict[str, str]:
        return {self._team_id_field: team_id, self._role_field: role}

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("队伍核心微服务尚未初始化")


def _team_id(user_id: str, request_id: str) -> str:
    return f"team-{uuid5(NAMESPACE_URL, f'{user_id}\0{request_id}').hex[:20]}"


def _team_value(team: TeamSnapshot) -> dict[str, object]:
    return {
        "队伍编号": team.team_id,
        "队长": team.leader_user_id,
        "成员": list(team.member_user_ids),
    }


def _invitation(
    value: Mapping[str, object], version: int, now: datetime
) -> TeamInvitation:
    expires_at = _time(value.get("到期时间"), "队伍邀请.到期时间")
    return TeamInvitation(
        _text(value.get("邀请者"), "队伍邀请.邀请者"),
        _text(value.get("目标"), "队伍邀请.目标"),
        _text(value.get("队伍编号"), "队伍邀请.队伍编号"),
        expires_at,
        version,
        now >= expires_at,
    )


def _texts(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TeamRuleError("team_snapshot_invalid")
    return tuple(_text(item, label) for item in value)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise TeamRuleError("invalid_text")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise JsonDataError(f"{label}必须是布尔值")
    return value


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _time(value: object, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise TeamRuleError("invitation_time_invalid") from exc
    return _utc(parsed)


__all__ = ["INVITATION_STATE", "MAIN_KEY", "TEAM_STATE", "TeamService"]
