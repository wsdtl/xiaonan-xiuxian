"""宗门山门进出：只处理宗门洞天准入和同行空间切换。"""

from __future__ import annotations

from game.core.action_group import ActionGroup, ActionGroupError, ActionGroupService
from game.core.sect import SectSnapshot, SectService

from collections.abc import Mapping

from game.core.data import JsonDataService, nonempty_text as _text
from game.core.location import (
    LocationConflictError,
    LocationService,
    SpaceChangeCommand,
)
from game.core.player_state import PlayerStateService
from game.core.world import LocationQuery, WorldService
from game.features.presentation import require_mapping

from .contracts import GateAction, GateCopy, GateFeatureError, GateResult


class GateFeature:
    def __init__(
        self,
        data: JsonDataService,
        sect: SectService,
        location: LocationService,
        player_state: PlayerStateService,
        action_group: ActionGroupService,
        world: WorldService,
    ) -> None:
        self._data = data
        self._sect = sect
        self._location = location
        self._player_state = player_state
        self._action_group = action_group
        self._world = world
        self._copy: GateCopy | None = None
        self._buttons: tuple[Mapping[str, str], ...] = ()
        self._space_type = ""
        self._enter_guard = ""

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("山门玩法已经初始化")
        if not self._sect.status().initialized:
            raise RuntimeError("宗门核心必须先于山门玩法启动")
        if not self._location.status().initialized:
            raise RuntimeError("位置核心必须先于山门玩法启动")
        if not self._action_group.status().initialized:
            raise RuntimeError("行动编排核心必须先于山门玩法启动")
        if not self._world.status().initialized:
            raise RuntimeError("世界核心必须先于山门玩法启动")
        rule = require_mapping(self._data.dataset("宗门规则").get("山门"), "山门.json")
        self._space_type = _text(rule.get("空间类型"), "山门.空间类型")
        # 山门在哪由**数据**决定：世界核心保证「宗门」是唯一的地点专属功能，
        # 这里读它的配置，顺便把守卫也取出来（声明有人读，不是摆设）。
        gate = self._world.feature_config("宗门")
        self._enter_guard = _text(gate.get("状态守卫"), "宗门.状态守卫")
        # 入山门/出山门命令已删，山门只做到达/离开时的自动空间切换，不再读展示。

    def copy(self) -> GateCopy:
        if self._copy is None:
            raise RuntimeError("山门玩法尚未初始化")
        return self._copy

    async def gate_actions(self, user_id: str) -> tuple[GateAction, ...]:
        self._require_initialized()
        member = await self._sect.membership(user_id)
        if member is None:
            return ()
        current = await self._location.current(user_id)
        sect = await self._sect.sect(member.sect_id)
        if sect is None:
            return ()
        if current.space_type == self._space_type and current.space_id == sect.cave_id:
            return actions(self._buttons, "宗门洞天")
        if current.space_type == "地表" and self._at_gate(current.xy):
            return actions(self._buttons, "宗门园区")
        return ()

    async def leave_if_available(self, user_id: str, request_id: str) -> bool:
        """离开宗门园区时自动回地表；不在洞天就静默跳过。"""

        self._require_initialized()
        member = await self._sect.membership(user_id)
        if member is None:
            return False
        sect = await self._sect.sect(member.sect_id)
        if sect is None:
            return False
        current = await self._location.current(user_id)
        if current.space_type != self._space_type or current.space_id != sect.cave_id:
            return False
        try:
            await self._location.change_space(
                SpaceChangeCommand(user_id, request_id + ":出洞天", (user_id,), "地表", "")
            )
        except LocationConflictError:
            return False
        return True

    async def enter_if_available(self, user_id: str, request_id: str) -> bool:
        """到达宗门园区即进入本宗洞天：没有宗门、没有位置或状态不允许时静默跳过。"""

        self._require_initialized()
        member = await self._sect.membership(user_id)
        if member is None:
            return False
        sect = await self._sect.sect(member.sect_id)
        if sect is None:
            return False
        current = await self._location.current(user_id)
        if current.space_type != "地表" or not self._at_gate(current.xy):
            return False
        try:
            await self._location.change_space(
                SpaceChangeCommand(
                    user_id,
                    request_id + ":入洞天",
                    (user_id,),
                    self._space_type,
                    sect.cave_id,
                )
            )
        except LocationConflictError:
            return False
        return True

    async def enter(self, user_id: str, request_id: str) -> GateResult:
        group = await self._resolve_group(user_id)
        sect = await self._member_sect(user_id)
        await self._require_group_same_sect(group.participant_user_ids, sect.sect_id)
        if group.mode != "personal" and group.leader_user_id != user_id:
            raise GateFeatureError("not_leader")
        locations = await self._location.current_many(group.participant_user_ids)
        await self._require_mutable_group(group.participant_user_ids)
        if any(
            value.space_type != "地表" or not self._at_gate(value.xy)
            for value in locations
        ):
            raise GateFeatureError("not_at_gate")
        try:
            await self._location.change_space(
                SpaceChangeCommand(
                    user_id,
                    request_id,
                    group.participant_user_ids,
                    self._space_type,
                    sect.cave_id,
                )
            )
        except LocationConflictError as exc:
            raise GateFeatureError("space_conflict") from exc
        return GateResult("进入", len(group.participant_user_ids))

    async def leave(self, user_id: str, request_id: str) -> GateResult:
        group = await self._resolve_group(user_id)
        sect = await self._member_sect(user_id)
        await self._require_group_same_sect(group.participant_user_ids, sect.sect_id)
        if group.mode != "personal" and group.leader_user_id != user_id:
            raise GateFeatureError("not_leader")
        locations = await self._location.current_many(group.participant_user_ids)
        await self._require_mutable_group(group.participant_user_ids)
        if any(
            value.space_type != self._space_type or value.space_id != sect.cave_id
            for value in locations
        ):
            raise GateFeatureError("not_in_cave")
        try:
            await self._location.change_space(
                SpaceChangeCommand(
                    user_id, request_id, group.participant_user_ids, "地表", ""
                )
            )
        except LocationConflictError as exc:
            raise GateFeatureError("space_conflict") from exc
        return GateResult("离开", len(group.participant_user_ids))

    async def _resolve_group(self, user_id: str) -> ActionGroup:
        try:
            return await self._action_group.resolve(user_id)
        except ActionGroupError as exc:
            if exc.code == "member_cannot_start":
                raise GateFeatureError("not_leader") from exc
            raise GateFeatureError("fellowship_conflict") from exc

    async def _member_sect(self, user_id: str) -> SectSnapshot:
        member = await self._sect.membership(user_id)
        if member is None:
            raise GateFeatureError("not_member")
        sect = await self._sect.sect(member.sect_id)
        if sect is None:
            raise GateFeatureError("sect_changed")
        return sect

    async def _require_group_same_sect(
        self, user_ids: tuple[str, ...], sect_id: str
    ) -> None:
        # 一次读完再按原顺序判：谁先不合格、报哪句话，与逐个读时一致。
        members = await self._sect.membership_many(user_ids)
        for member in members:
            if member is None or member.sect_id != sect_id:
                raise GateFeatureError("external_member")

    async def _require_mutable_group(self, user_ids: tuple[str, ...]) -> None:
        # 同上：批量读一次，判定仍按原顺序，第一个不通过的当场报出来。
        results = await self._player_state.authorize_many(
            user_ids, self._enter_guard or "自主空闲或休息"
        )
        for result in results:
            if not result.allowed:
                raise GateFeatureError("current_busy")

    def _at_gate(self, xy: tuple[int, int]) -> bool:
        """站在山门上吗——认的是地点功能，不是某一格坐标。"""

        return "宗门" in self._world.locate(LocationQuery(xy=xy)).available_functions

    def _require_initialized(self) -> None:
        if not self._space_type:
            raise RuntimeError("山门玩法尚未初始化")


__all__ = ["GateFeature"]
