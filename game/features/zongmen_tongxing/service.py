"""宗门同行玩法：召集、主动加入和成员管理。"""

from __future__ import annotations

from .contracts import (
    SectFollowAction,
    SectFollowCopy,
    SectFollowFeatureError,
    SectFollowMemberView,
    SectFollowPage,
    SectFollowResult,
)

from game.core.character import CharacterPublicProfile, CharacterService
from game.core.data import JsonDataService
from game.core.location import LocationService
from game.core.player_state import PlayerStateService
from game.core.sect import SectConflictError, SectService
from game.core.team import TeamService

from .presentation import actions, load_presentation


class SectFollowFeature:
    def __init__(
        self,
        data: JsonDataService,
        sect: SectService,
        character: CharacterService,
        location: LocationService,
        player_state: PlayerStateService,
        team: TeamService,
    ) -> None:
        self._data = data
        self._sect = sect
        self._character = character
        self._location = location
        self._player_state = player_state
        self._team = team
        self._copy: SectFollowCopy | None = None
        self._buttons = ()

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("宗门同行玩法微服务已经初始化")
        if not self._sect.status().initialized:
            raise RuntimeError("宗门核心必须先于宗门同行玩法启动")
        self._copy, self._buttons = load_presentation(self._data)

    def copy(self) -> SectFollowCopy:
        if self._copy is None:
            raise RuntimeError("宗门同行玩法微服务尚未初始化")
        return self._copy

    def page_actions(self, page: str) -> tuple[SectFollowAction, ...]:
        return actions(self._buttons, page)

    async def page(self, user_id: str) -> SectFollowPage:
        member = await self._sect.membership(user_id)
        if member is None:
            raise SectFollowFeatureError("not_member")
        sect = await self._sect.sect(member.sect_id)
        if sect is None:
            raise SectFollowFeatureError("sect_changed")
        group = await self._sect.follow(member.sect_id)
        if group is None:
            return SectFollowPage(
                "宗主未召集" if member.role == "宗主" else "等待召集",
                sect.name,
                maximum_members=self._sect.status().maximum_followers,
            )
        profiles = await self._profiles(group.member_user_ids)
        names = {profile.user_id: profile.name for profile in profiles}
        if user_id == group.leader_user_id:
            page = "宗主"
        elif user_id in group.member_user_ids:
            page = "同行中"
        else:
            page = "可加入"
        return SectFollowPage(
            page,
            sect.name,
            names.get(group.leader_user_id, group.leader_user_id),
            tuple(
                SectFollowMemberView(
                    member_id,
                    names.get(member_id, member_id),
                    "宗主" if member_id == group.leader_user_id else "同行成员",
                )
                for member_id in group.member_user_ids
            ),
            self._sect.status().maximum_followers,
        )

    async def assemble(self, user_id: str, request_id: str) -> SectFollowResult:
        await self._require_mutable(user_id)
        await self._require_not_in_team(user_id)
        try:
            await self._sect.assemble(user_id, request_id)
        except SectConflictError as exc:
            raise SectFollowFeatureError(exc.code) from exc
        return SectFollowResult("召集", "", await self.page(user_id))

    async def join(self, user_id: str, request_id: str) -> SectFollowResult:
        await self._require_mutable(user_id)
        await self._require_not_in_team(user_id)
        member = await self._sect.membership(user_id)
        if member is None:
            raise SectFollowFeatureError("not_member")
        group = await self._sect.follow(member.sect_id)
        if group is None:
            raise SectFollowFeatureError("follow_not_started")
        await self._require_same_location(user_id, group.leader_user_id)
        try:
            await self._sect.join_follow(user_id, request_id)
        except SectConflictError as exc:
            raise SectFollowFeatureError(exc.code) from exc
        return SectFollowResult("加入", "", await self.page(user_id))

    async def leave(self, user_id: str, request_id: str) -> SectFollowResult:
        await self._require_mutable(user_id)
        try:
            await self._sect.leave_follow(user_id, request_id)
        except SectConflictError as exc:
            raise SectFollowFeatureError(exc.code) from exc
        return SectFollowResult("离开", "", await self.page(user_id))

    async def kick(
        self, user_id: str, target: str, request_id: str
    ) -> SectFollowResult:
        await self._require_mutable(user_id)
        profile = await self._resolve_follow_member(user_id, target)
        await self._require_mutable(profile.user_id)
        try:
            await self._sect.kick_follow(user_id, profile.user_id, request_id)
        except SectConflictError as exc:
            raise SectFollowFeatureError(exc.code) from exc
        return SectFollowResult("请离", profile.name, await self.page(user_id))

    async def disband(self, user_id: str, request_id: str) -> SectFollowResult:
        await self._require_mutable(user_id)
        try:
            await self._sect.disband_follow(user_id, request_id)
        except SectConflictError as exc:
            raise SectFollowFeatureError(exc.code) from exc
        return SectFollowResult("解散", "", await self.page(user_id))

    async def _resolve_follow_member(
        self, user_id: str, query: str
    ) -> CharacterPublicProfile:
        membership = await self._sect.follow_membership(user_id)
        if membership is None:
            raise SectFollowFeatureError("not_following")
        normalized = str(query or "").strip()
        if not normalized:
            raise SectFollowFeatureError("target_missing")
        profiles = await self._profiles(membership.member_user_ids)
        exact = next((value for value in profiles if value.user_id == normalized), None)
        if exact is not None:
            return exact
        matches = tuple(value for value in profiles if value.name == normalized)
        if not matches:
            raise SectFollowFeatureError("target_not_following")
        if len(matches) > 1:
            raise SectFollowFeatureError("target_ambiguous")
        return matches[0]

    async def _profiles(
        self, user_ids: tuple[str, ...]
    ) -> tuple[CharacterPublicProfile, ...]:
        profiles = await self._character.public_profiles(user_ids)
        if len(profiles) != len(user_ids):
            raise SectFollowFeatureError("sect_changed")
        return profiles

    async def _require_mutable(self, user_id: str) -> None:
        guard = await self._player_state.authorize(user_id, "自主空闲或休息")
        if not guard.allowed:
            raise SectFollowFeatureError("actor_busy")

    async def _require_not_in_team(self, user_id: str) -> None:
        if await self._team.membership(user_id) is not None:
            raise SectFollowFeatureError("fellowship_conflict")

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
            raise SectFollowFeatureError("not_same_location")


__all__ = ["SectFollowFeature"]
