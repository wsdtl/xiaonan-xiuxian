"""宗门关系玩法：解析目标、校验同处和生成宗门页面。"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from game.core.character import CharacterPublicProfile, CharacterService
from game.core.location import (
    LocationConflictError,
    LocationService,
    SpaceChangeCommand,
)
from game.core.player_state import PlayerStateService
from game.core.sect import SectConflictError, SectService
from game.core.sect_progress import SectProgressService
from game.core.sect_library import SectLibraryError, SectLibraryService
from game.core.world import LocationQuery, WorldService

from .contracts import (
    SectCopy,
    SectFeatureError,
    SectMemberView,
    SectOperationResult,
    SectPage,
)
from .presentation import actions, load_presentation


class SectFeature:
    def __init__(
        self,
        data,
        sect: SectService,
        character: CharacterService,
        location: LocationService,
        world: WorldService,
        player_state: PlayerStateService,
        progress: SectProgressService | None = None,
        library: SectLibraryService | None = None,
    ) -> None:
        self._data = data
        self._sect = sect
        self._character = character
        self._location = location
        self._world = world
        self._player_state = player_state
        self._progress = progress
        self._library = library
        self._copy: SectCopy | None = None
        self._buttons = ()

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("宗门玩法微服务已经初始化")
        if not self._sect.status().initialized:
            raise RuntimeError("宗门核心必须先于宗门玩法启动")
        self._copy, self._buttons = load_presentation(self._data)

    def copy(self) -> SectCopy:
        if self._copy is None:
            raise RuntimeError("宗门玩法微服务尚未初始化")
        return self._copy

    def page_actions(self, page: str):
        return actions(self._buttons, page)

    async def page(self, user_id: str, *, now: datetime | None = None) -> SectPage:
        invitation = await self._sect.pending_invitation(user_id, now=now)
        member = await self._sect.membership(user_id)
        if member is None:
            if invitation is not None and not invitation.expired:
                current = now or datetime.now(timezone.utc)
                remaining = max(
                    1, math.ceil((invitation.expires_at - current).total_seconds() / 60)
                )
                inviter = await self._profile(invitation.inviter_user_id)
                return SectPage(
                    "待处理邀请",
                    invitation_name=invitation.sect_name,
                    invitation_inviter_name=inviter.name,
                    invitation_minutes=remaining,
                )
            return SectPage("未加入")
        sect = await self._sect.sect(member.sect_id)
        if sect is None:
            raise SectFeatureError("宗门变化")
        members = await self._sect.members(member.sect_id)
        profiles = await self._character.public_profiles(
            tuple(value.user_id for value in members)
        )
        names = {value.user_id: value.name for value in profiles}
        place = self._world.locate(LocationQuery(xy=sect.entrance_xy))
        progress = (
            await self._progress.snapshot(member.sect_id) if self._progress else None
        )
        return SectPage(
            member.role,
            sect.name,
            names.get(sect.leader_user_id, sect.leader_user_id),
            f"{place.location_name} · ({sect.entrance_xy[0]}, {sect.entrance_xy[1]})",
            sect.cave_id,
            tuple(
                SectMemberView(
                    value.user_id, names.get(value.user_id, value.user_id), value.role
                )
                for value in members
            ),
            sect_level=progress.level if progress else 0,
            maximum_sect_level=progress.maximum_level if progress else 0,
            total_contribution=progress.total_contribution if progress else 0,
            next_level_contribution=progress.next_level_contribution if progress else None,
            production_multiplier=progress.production_multiplier if progress else 1.0,
            gathering_multiplier=progress.gathering_multiplier if progress else 1.0,
            facility_cost_multiplier=progress.facility_cost_multiplier if progress else 1.0,
        )

    async def create(
        self, user_id: str, request_id: str, name: str
    ) -> SectOperationResult:
        await self._require_same_location_target(user_id, user_id)
        current = await self._location.current(user_id)
        if current.space_type != "地表":
            raise SectFeatureError("not_surface")
        try:
            sect = await self._sect.create(user_id, request_id, name, current.xy)
        except SectConflictError as exc:
            raise SectFeatureError(exc.code) from exc
        return SectOperationResult("创建", sect.name, await self.page(user_id))

    async def invite(
        self, user_id: str, target: str, request_id: str
    ) -> SectOperationResult:
        profile = await self._resolve_nearby(user_id, target)
        await self._require_mutable(profile.user_id)
        try:
            await self._sect.invite(user_id, profile.user_id, request_id)
        except SectConflictError as exc:
            raise SectFeatureError(exc.code) from exc
        return SectOperationResult("邀请", profile.name, await self.page(user_id))

    async def accept(self, user_id: str, request_id: str) -> SectOperationResult:
        invitation = await self._sect.pending_invitation(user_id)
        if invitation is None:
            raise SectFeatureError("invitation_missing")
        await self._require_same_location_target(user_id, invitation.inviter_user_id)
        try:
            await self._sect.accept(user_id, request_id)
        except SectConflictError as exc:
            raise SectFeatureError(exc.code) from exc
        return SectOperationResult("接受", invitation.sect_name, await self.page(user_id))

    async def reject(self, user_id: str, request_id: str) -> SectOperationResult:
        invitation = await self._sect.pending_invitation(user_id)
        if invitation is None:
            raise SectFeatureError("invitation_missing")
        inviter = await self._profile(invitation.inviter_user_id)
        try:
            await self._sect.reject(user_id, request_id)
        except SectConflictError as exc:
            raise SectFeatureError(exc.code) from exc
        return SectOperationResult("拒绝", inviter.name, await self.page(user_id))

    async def leave(self, user_id: str, request_id: str) -> SectOperationResult:
        try:
            await self._sect.leave(user_id, request_id)
        except SectConflictError as exc:
            raise SectFeatureError(exc.code) from exc
        finally:
            await self._clear_borrowed(user_id, request_id)
        return SectOperationResult("退出", "", await self.page(user_id))

    async def kick(
        self, user_id: str, target: str, request_id: str
    ) -> SectOperationResult:
        member = await self._resolve_member(user_id, target)
        try:
            await self._sect.kick(user_id, member.user_id, request_id)
        except SectConflictError as exc:
            raise SectFeatureError(exc.code) from exc
        finally:
            await self._clear_borrowed(member.user_id, request_id)
        return SectOperationResult("逐出", member.name, await self.page(user_id))

    async def transfer(
        self, user_id: str, target: str, request_id: str
    ) -> SectOperationResult:
        member = await self._resolve_member(user_id, target)
        try:
            await self._sect.transfer(user_id, member.user_id, request_id)
        except SectConflictError as exc:
            raise SectFeatureError(exc.code) from exc
        return SectOperationResult("转让", member.name, await self.page(user_id))

    async def appoint_elder(
        self, user_id: str, target: str, request_id: str
    ) -> SectOperationResult:
        member = await self._resolve_member(user_id, target)
        try:
            await self._sect.appoint_elder(user_id, member.user_id, request_id)
        except SectConflictError as exc:
            raise SectFeatureError(exc.code) from exc
        return SectOperationResult("任命长老", member.name, await self.page(user_id))

    async def remove_elder(
        self, user_id: str, target: str, request_id: str
    ) -> SectOperationResult:
        member = await self._resolve_member(user_id, target)
        try:
            await self._sect.remove_elder(user_id, member.user_id, request_id)
        except SectConflictError as exc:
            raise SectFeatureError(exc.code) from exc
        return SectOperationResult("罢免长老", member.name, await self.page(user_id))

    async def disband(self, user_id: str, request_id: str) -> SectOperationResult:
        member = await self._sect.membership(user_id)
        if member is None:
            raise SectFeatureError("not_member")
        members = await self._sect.members(member.sect_id)
        try:
            await self._sect.disband(user_id, request_id)
        except SectConflictError as exc:
            raise SectFeatureError(exc.code) from exc
        finally:
            for value in members:
                await self._clear_borrowed(value.user_id, request_id)
        cave_users = []
        for value in members:
            location = await self._location.current(value.user_id)
            if location.space_type == "宗门洞天":
                cave_users.append(value.user_id)
        if cave_users:
            try:
                await self._location.change_space(
                    SpaceChangeCommand(
                        user_id,
                        f"{request_id}:清理洞天",
                        tuple(cave_users),
                        "地表",
                        "",
                    )
                )
            except LocationConflictError as exc:
                raise SectFeatureError("洞天位置清理失败") from exc
        return SectOperationResult("解散", "", await self.page(user_id))

    async def _clear_borrowed(self, user_id: str, request_id: str) -> None:
        """成员关系终止后清掉藏经阁借阅并还原原功法（规则的三条失效条件）。

        三条失效条件都走成员删除：退出与逐出删一个人的成员记录，解散清空全部成员记录。
        清理排在核心事务之后（`finally`，失败也要清），清完借阅记录就不在了，重复调用
        自然变成空操作；读取构筑那一侧的还原仍留着兜底，所以中途出错也不会让借阅复活。
        """

        if self._library is None:
            return
        try:
            await self._library.clear_borrowed(user_id, f"{request_id}:清除借阅")
        except SectLibraryError as exc:
            raise SectFeatureError("借阅功法清理失败") from exc

    async def _resolve_nearby(self, user_id: str, query: str) -> CharacterPublicProfile:
        normalized = str(query or "").strip()
        if not normalized:
            raise SectFeatureError("target_missing")
        nearby = await self._location.nearby_players(user_id)
        same_place = tuple(
            value.user_id for value in nearby.values if value.xy == nearby.origin.xy
        )
        profiles = await self._profiles(same_place)
        exact = next((value for value in profiles if value.user_id == normalized), None)
        if exact is not None:
            return exact
        matches = tuple(value for value in profiles if value.name == normalized)
        if not matches:
            raise SectFeatureError("target_not_found")
        if len(matches) > 1:
            raise SectFeatureError("target_ambiguous")
        return matches[0]

    async def _resolve_member(self, user_id: str, query: str) -> CharacterPublicProfile:
        member = await self._sect.membership(user_id)
        if member is None:
            raise SectFeatureError("not_member")
        normalized = str(query or "").strip()
        if not normalized:
            raise SectFeatureError("target_missing")
        profiles = await self._profiles(
            tuple(value.user_id for value in await self._sect.members(member.sect_id))
        )
        exact = next((value for value in profiles if value.user_id == normalized), None)
        if exact is not None:
            return exact
        matches = tuple(value for value in profiles if value.name == normalized)
        if not matches:
            raise SectFeatureError("target_not_member")
        if len(matches) > 1:
            raise SectFeatureError("target_ambiguous")
        return matches[0]

    async def _profiles(self, user_ids: tuple[str, ...]):
        profiles = await self._character.public_profiles(user_ids)
        if len(profiles) != len(user_ids):
            raise SectFeatureError("sect_changed")
        return profiles

    async def _profile(self, user_id: str):
        profiles = await self._profiles((user_id,))
        return profiles[0]

    async def _require_mutable(self, user_id: str) -> None:
        result = await self._player_state.authorize(user_id, "自主空闲或休息")
        if not result.allowed:
            raise SectFeatureError("target_busy")

    async def _require_same_location_target(self, first: str, second: str) -> None:
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
            raise SectFeatureError("not_same_location")


__all__ = ["SectFeature"]
