"""角色名解析、同处校验与队伍核心编排。"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from game.core.character import CharacterPublicProfile, CharacterService
from game.core.data import JsonDataService
from game.core.location import LocationService
from game.core.player_state import PlayerStateService
from game.core.team import TeamError, TeamInvitation, TeamService

from .contracts import (
    TeamAction,
    TeamCopy,
    TeamFeatureError,
    TeamInvitationView,
    TeamMemberView,
    TeamOperationResult,
    TeamPage,
)
from .presentation import actions, load_presentation


class TeamFeature:
    def __init__(
        self,
        data: JsonDataService,
        team: TeamService,
        character: CharacterService,
        location: LocationService,
        player_state: PlayerStateService,
    ) -> None:
        self._data = data
        self._team = team
        self._character = character
        self._location = location
        self._player_state = player_state
        self._copy: TeamCopy | None = None
        self._buttons = ()

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("队伍玩法微服务已经初始化")
        if not self._team.status().initialized:
            raise RuntimeError("队伍核心必须先于队伍玩法启动")
        self._copy, self._buttons = load_presentation(self._data)

    def copy(self) -> TeamCopy:
        if self._copy is None:
            raise RuntimeError("队伍玩法微服务尚未初始化")
        return self._copy

    def page_actions(self, value: TeamPage) -> tuple[TeamAction, ...]:
        self.copy()
        result = actions(self._buttons, value.page)
        if len(value.members) >= value.maximum_players:
            return tuple(action for action in result if "invite" not in action.action_id)
        return result

    async def page(self, user_id: str, *, now: datetime | None = None) -> TeamPage:
        self.copy()
        current_time = _utc(now)
        try:
            membership = await self._team.membership(user_id)
            invitation = await self._team.pending_invitation(user_id, now=current_time)
        except TeamError as exc:
            raise TeamFeatureError(exc.code) from exc
        if membership is None:
            if invitation is not None and not invitation.expired:
                inviter = await self._profile(invitation.inviter_user_id)
                remaining = max(
                    1,
                    math.ceil(
                        (invitation.expires_at - current_time).total_seconds() / 60
                    ),
                )
                return TeamPage(
                    "待处理邀请",
                    self._team.status().maximum_players,
                    invitation=TeamInvitationView(inviter.name, remaining),
                )
            return TeamPage("未组队", self._team.status().maximum_players)
        profiles = await self._profiles(membership.team.member_user_ids)
        by_user = {profile.user_id: profile for profile in profiles}
        members = tuple(
            TeamMemberView(
                member,
                by_user[member].name,
                "队长" if member == membership.team.leader_user_id else "队员",
            )
            for member in membership.team.member_user_ids
        )
        return TeamPage(
            "队长" if membership.user_id == membership.team.leader_user_id else "队员",
            self._team.status().maximum_players,
            members,
        )

    async def invite(
        self, user_id: str, target: str, request_id: str
    ) -> TeamOperationResult:
        await self._require_mutable(user_id)
        profile = await self._resolve_nearby(user_id, target)
        await self._require_mutable(profile.user_id, target=True)
        try:
            await self._team.invite(user_id, profile.user_id, request_id)
        except TeamError as exc:
            raise TeamFeatureError(exc.code) from exc
        return TeamOperationResult("邀请", profile.name, await self.page(user_id))

    async def accept(self, user_id: str, request_id: str) -> TeamOperationResult:
        await self._require_mutable(user_id)
        invitation = await self._active_invitation(user_id)
        inviter = await self._profile(invitation.inviter_user_id)
        await self._require_same_location(user_id, invitation.inviter_user_id)
        try:
            await self._team.accept(user_id, request_id)
        except TeamError as exc:
            raise TeamFeatureError(exc.code) from exc
        return TeamOperationResult("接受", inviter.name, await self.page(user_id))

    async def reject(self, user_id: str, request_id: str) -> TeamOperationResult:
        invitation = await self._active_invitation(user_id, allow_expired=True)
        inviter = await self._profile(invitation.inviter_user_id)
        try:
            await self._team.reject(user_id, request_id)
        except TeamError as exc:
            raise TeamFeatureError(exc.code) from exc
        return TeamOperationResult("拒绝", inviter.name, await self.page(user_id))

    async def leave(self, user_id: str, request_id: str) -> TeamOperationResult:
        await self._require_mutable(user_id)
        try:
            await self._team.leave(user_id, request_id)
        except TeamError as exc:
            raise TeamFeatureError(exc.code) from exc
        return TeamOperationResult("离开", "", await self.page(user_id))

    async def kick(
        self, user_id: str, target: str, request_id: str
    ) -> TeamOperationResult:
        await self._require_mutable(user_id)
        profile = await self._resolve_member(user_id, target)
        try:
            await self._team.kick(user_id, profile.user_id, request_id)
        except TeamError as exc:
            raise TeamFeatureError(exc.code) from exc
        return TeamOperationResult("请离", profile.name, await self.page(user_id))

    async def transfer(
        self, user_id: str, target: str, request_id: str
    ) -> TeamOperationResult:
        await self._require_mutable(user_id)
        profile = await self._resolve_member(user_id, target)
        try:
            await self._team.transfer(user_id, profile.user_id, request_id)
        except TeamError as exc:
            raise TeamFeatureError(exc.code) from exc
        return TeamOperationResult("移交", profile.name, await self.page(user_id))

    async def disband(self, user_id: str, request_id: str) -> TeamOperationResult:
        await self._require_mutable(user_id)
        try:
            await self._team.disband(user_id, request_id)
        except TeamError as exc:
            raise TeamFeatureError(exc.code) from exc
        return TeamOperationResult("解散", "", await self.page(user_id))

    async def _active_invitation(
        self, user_id: str, *, allow_expired: bool = False
    ) -> TeamInvitation:
        try:
            invitation = await self._team.pending_invitation(user_id)
        except TeamError as exc:
            raise TeamFeatureError(exc.code) from exc
        if invitation is None:
            raise TeamFeatureError("invitation_missing")
        if invitation.expired and not allow_expired:
            raise TeamFeatureError("invitation_expired")
        return invitation

    async def _resolve_nearby(self, user_id: str, query: str) -> CharacterPublicProfile:
        normalized = str(query or "").strip()
        if not normalized:
            raise TeamFeatureError("target_missing")
        candidates = await self._location.nearby_players(user_id)
        same_place = tuple(
            candidate.user_id
            for candidate in candidates.values
            if candidate.xy == candidates.origin.xy
        )
        profiles = await self._profiles(same_place)
        exact_id = next(
            (profile for profile in profiles if profile.user_id == normalized), None
        )
        if exact_id is not None:
            return exact_id
        matches = tuple(profile for profile in profiles if profile.name == normalized)
        if not matches:
            raise TeamFeatureError("target_not_found")
        if len(matches) > 1:
            raise TeamFeatureError("target_ambiguous")
        return matches[0]

    async def _resolve_member(self, user_id: str, query: str) -> CharacterPublicProfile:
        normalized = str(query or "").strip()
        if not normalized:
            raise TeamFeatureError("target_missing")
        try:
            membership = await self._team.membership(user_id)
        except TeamError as exc:
            raise TeamFeatureError(exc.code) from exc
        if membership is None:
            raise TeamFeatureError("not_grouped")
        profiles = await self._profiles(membership.team.member_user_ids)
        exact_id = next(
            (profile for profile in profiles if profile.user_id == normalized), None
        )
        if exact_id is not None:
            return exact_id
        matches = tuple(profile for profile in profiles if profile.name == normalized)
        if not matches:
            raise TeamFeatureError("target_not_member")
        if len(matches) > 1:
            raise TeamFeatureError("target_ambiguous")
        return matches[0]

    async def _require_same_location(self, first: str, second: str) -> None:
        first_location = await self._location.current(first)
        second_location = await self._location.current(second)
        if (
            first_location.space_type,
            first_location.space_id,
            first_location.xy,
        ) != (
            second_location.space_type,
            second_location.space_id,
            second_location.xy,
        ):
            raise TeamFeatureError("not_same_location")

    async def _require_mutable(self, user_id: str, *, target: bool = False) -> None:
        guard = await self._player_state.authorize(user_id, "自主空闲或休息")
        if not guard.allowed:
            raise TeamFeatureError("target_busy" if target else "actor_busy")

    async def _profile(self, user_id: str) -> CharacterPublicProfile:
        profiles = await self._profiles((user_id,))
        if not profiles:
            raise TeamFeatureError("target_not_found")
        return profiles[0]

    async def _profiles(
        self, user_ids: tuple[str, ...]
    ) -> tuple[CharacterPublicProfile, ...]:
        profiles = await self._character.public_profiles(user_ids)
        if len(profiles) != len(user_ids):
            raise TeamFeatureError("team_changed")
        return profiles


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


__all__ = ["TeamFeature"]
