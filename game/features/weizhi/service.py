"""当前位置、本地修士和附近对象的玩法编排。"""

from __future__ import annotations

from game.core.location import LocationService

import asyncio
import math
from collections.abc import Mapping, Sequence
from dataclasses import replace

from game.core.character import CharacterService
from game.core.companion import CompanionError
from game.core.character.contracts import CharacterPublicProfile

from .contracts import CompanionView
from game.core.companion import CompanionService, LocalCultivator
from game.core.data import JsonDataError, JsonDataService, positive_int as _positive_int
from game.core.player_state import PlayerStateService
from game.core.sect import SectService
from game.core.team import TeamService
from game.core.world import LocationQuery, LocationView, WorldService
from game.features.presentation import require_mapping

from .contracts import (
    StatusView,
    CurrentPositionView,
    NearbyCultivatorPage,
    NearbyCultivatorView,
    NearbyOverview,
    NearbyPageError,
    NearbyWorldLocation,
    NearbyWorldLocations,
    PositionAction,
    PositionCopy,
)
from .presentation import ButtonTemplate, load_position_presentation, render_action


class PositionFeature:
    """组合位置、世界、人物公开摘要、状态和本地修士。"""

    def __init__(
        self,
        data: JsonDataService,
        world: WorldService,
        location: LocationService,
        character: CharacterService,
        player_state: PlayerStateService,
        companion: CompanionService,
        team: TeamService,
        sect: SectService,
    ) -> None:
        self._data = data
        self._world = world
        self._location = location
        self._character = character
        self._player_state = player_state
        self._companion = companion
        self._team = team
        self._sect = sect
        self._initialized = False
        self._location_radius_meters = 0
        self._location_limit = 0
        self._meters_per_li = 0
        self._rounding_step = 0
        self._same_place = ""
        self._open_functions: frozenset[str] = frozenset()
        self._directions: Mapping[tuple[int, int], str] = {}
        self._copy: PositionCopy | None = None
        self._buttons: tuple[ButtonTemplate, ...] = ()

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("位置查看玩法微服务已经初始化")
        for initialized, label in (
            (self._world.status().initialized, "世界核心"),
            (self._location.status().initialized, "玩家位置核心"),
            (self._character.status().initialized, "角色核心"),
            (self._player_state.status().initialized, "人物状态核心"),
            (self._companion.status().initialized, "世界道侣核心"),
            (self._sect.status().initialized, "宗门核心"),
        ):
            if not initialized:
                raise RuntimeError(f"{label}必须先于位置查看玩法启动")
        nearby = self._data.dataset("位置页面规则").get("附近")
        nearby_rule = require_mapping(nearby, "附近.json")
        location_rule = require_mapping(nearby_rule.get("地点"), "附近.地点")
        self._location_radius_meters = _positive_int(
            location_rule.get("范围米数"), "附近.地点.范围米数"
        )
        self._location_limit = _positive_int(
            location_rule.get("最多数量"), "附近.地点.最多数量"
        )
        presentation = load_position_presentation(self._data.dataset("位置页面文案"))
        self._validate_function_buttons(presentation.open_functions)
        self._meters_per_li = presentation.meters_per_li
        self._rounding_step = presentation.rounding_step
        self._same_place = presentation.same_place
        self._open_functions = presentation.open_functions
        self._directions = presentation.directions
        self._copy = presentation.copy
        self._buttons = presentation.buttons
        self._initialized = True

    def copy(self) -> PositionCopy:
        self._require_initialized()
        if self._copy is None:
            raise RuntimeError("位置展示文案尚未初始化")
        return self._copy

    def position_actions(
        self,
        functions: Sequence[str],
        *,
        plant_pool: Sequence[str] = (),
        mineral_pool: Sequence[str] = (),
    ) -> tuple[PositionAction, ...]:
        self._require_initialized()
        return (
            self.location_actions(functions)
            + self.terrain_actions(plant_pool, mineral_pool)
            + self._actions_for("位置")
        )

    def open_location_functions(self, functions: Sequence[str]) -> tuple[str, ...]:
        """只返回已经建立玩家入口的地点功能。"""

        self._require_initialized()
        return self._visible_functions(functions)

    def location_actions(self, functions: Sequence[str]) -> tuple[PositionAction, ...]:
        """按地点已经开放的功能生成当前可用按钮。"""

        self._require_initialized()
        available = set(self.open_location_functions(functions))
        return tuple(
            render_action(template, {})
            for template in self._buttons
            if template.page == "地点功能" and template.function in available
        )

    def terrain_actions(
        self,
        plant_pool: Sequence[str],
        mineral_pool: Sequence[str],
    ) -> tuple[PositionAction, ...]:
        """按世界核心返回的地形资源池生成采药、采矿按钮。"""

        self._require_initialized()
        available = set()
        if plant_pool:
            available.add("灵植池")
        if mineral_pool:
            available.add("灵矿池")
        return tuple(
            render_action(template, {})
            for template in self._buttons
            if template.page == "地点功能" and template.function in available
        )

    async def current_location_actions(
        self, user_id: str
    ) -> tuple[PositionAction, ...]:
        """为地点专属回复取得当前地点的完整操作面板。"""

        self._require_initialized()
        current = await self._location.current(user_id)
        location = self._world.locate(LocationQuery(xy=current.xy))
        if current.space_type != "地表":
            return self.position_actions(())
        return self.position_actions(
            location.available_functions,
            plant_pool=location.plant_pool,
            mineral_pool=location.mineral_pool,
        )

    def nearby_overview_actions(
        self,
        locations: Sequence[NearbyWorldLocation] = (),
        *,
        surface: bool = True,
    ) -> tuple[PositionAction, ...]:
        self._require_initialized()
        return self._location_entry_actions(locations) + self._actions_for(
            "概览", surface=surface
        )

    def format_actions(self) -> tuple[PositionAction, ...]:
        """格式与提示类回执的动作：只给「查看帮助」。"""

        return self._actions_for("格式")


    def nearby_cultivator_actions(
        self, page: int, has_next: bool, *, surface: bool = True
    ) -> tuple[PositionAction, ...]:
        self._require_initialized()
        result: list[PositionAction] = []
        for template in self._buttons:
            if template.page != "修士":
                continue
            if template.condition == "地表":
                if not surface:
                    continue
                variables = {}
            elif template.condition == "有上一页":
                if page <= 1:
                    continue
                variables = {"页码": page - 1}
            elif template.condition == "有下一页":
                if not has_next:
                    continue
                variables = {"页码": page + 1}
            else:
                variables = {}
            result.append(render_action(template, variables))
        return tuple(result)

    def nearby_location_actions(
        self, locations: Sequence[NearbyWorldLocation]
    ) -> tuple[PositionAction, ...]:
        self._require_initialized()
        result = list(self._location_entry_actions(locations))
        result.extend(self._actions_for("地点"))
        return tuple(result)

    def status_copy(self) -> dict:
        """快捷状态页的文案（读「快捷页面文案」数据集）。"""

        return dict(self._data.dataset("快捷页面文案").get("状态") or {})

    async def status_summary(self, user_id: str) -> StatusView:
        """只看现在在干什么：位置、空间、状态标签与可用守卫。"""

        if not self._initialized:
            raise RuntimeError("位置查看玩法微服务尚未初始化")
        position = await self.current(user_id)
        snapshot = await self._player_state.current(user_id)
        names = tuple(
            slot.name for slot in (snapshot.states.values() if snapshot else ())
        )
        return StatusView(
            place_name=position.location.location_name,
            xy=position.location.xy,
            space_type=position.space_type,
            space_name=position.space_name,
            states=names,
            guards=(),
        )

    async def current(self, user_id: str) -> CurrentPositionView:
        self._require_initialized()
        current, active = await asyncio.gather(
            self._location.current(user_id),
            self._companion.active(user_id),
        )
        location = self._visible_location(
            self._world.locate(LocationQuery(xy=current.xy))
        )
        if current.space_type != "地表":
            location = replace(
                location,
                available_functions=(),
                plant_pool=(),
                mineral_pool=(),
                companion_pool=(),
            )
        excluded = (active.companion_id,) if active is not None else ()
        local = (
            self._companion.local_cultivators(
                location.location_name,
                exclude_companion_ids=excluded,
            )
            if location.companion_pool and current.space_type == "地表"
            else ()
        )
        space_name = ""
        if current.space_type != "地表":
            member = await self._sect.membership(user_id)
            sect = await self._sect.sect(member.sect_id) if member is not None else None
            space_name = (
                f"{sect.name}洞天"
                if sect is not None and sect.cave_id == current.space_id
                else current.space_type
            )
        return CurrentPositionView(
            location,
            local,
            self._active_summary(active.companion_id) if active is not None else None,
            current.space_type,
            space_name,
        )

    async def nearby_overview(self, user_id: str) -> NearbyOverview:
        self._require_initialized()
        current, cultivators, locations = await asyncio.gather(
            self.current(user_id),
            self.nearby_cultivators(user_id),
            self.nearby_locations(user_id),
        )
        return NearbyOverview(
            current=current,
            visiting_cultivator_count=cultivators.visible_count,
            locations=locations.values,
        )

    async def nearby_cultivators(
        self, user_id: str, page: int = 1
    ) -> NearbyCultivatorPage:
        self._require_initialized()
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise NearbyPageError(self.copy().invalid_page)
        candidates, active = await asyncio.gather(
            self._location.nearby_players(user_id),
            self._companion.active(user_id),
        )
        user_ids = tuple(value.user_id for value in candidates.values)
        profiles, states, teams, sect_follows = await asyncio.gather(
            self._character.public_profiles(user_ids),
            self._player_state.public_many(user_ids),
            self._team.public_many(user_ids),
            self._sect.public_follow_many(user_ids),
        )
        profile_by_user = {value.user_id: value for value in profiles}
        state_by_user = {value.user_id: value for value in states}
        team_by_user = {value.user_id: value for value in teams}
        sect_follow_by_user = {value.user_id: value for value in sect_follows}
        visible: list[NearbyCultivatorView] = []
        for candidate in candidates.values:
            profile = profile_by_user.get(candidate.user_id)
            state = state_by_user.get(candidate.user_id)
            team = team_by_user.get(candidate.user_id)
            sect_follow = sect_follow_by_user.get(candidate.user_id)
            if profile is None or state is None or not state.appears_nearby:
                continue
            names = state.names
            if (
                sect_follow is not None
                and sect_follow.following
                and team is not None
                and team.grouped
            ):
                names += (self.copy().fellowship_conflict_state,)
            elif sect_follow is not None and sect_follow.following:
                names += (
                    self.copy().sect_follow_leader_state.format_map(
                        {"人数": sect_follow.member_count}
                    )
                    if sect_follow.leading
                    else self.copy().sect_follow_member_state,
                )
            elif team is not None and team.grouped:
                names += (self.copy().team_state.format_map({"人数": team.member_count}),)
            visible.append(
                NearbyCultivatorView(
                    user_id=candidate.user_id,
                    name=profile.name,
                    gender=profile.gender,
                    realm_name=profile.realm_name,
                    level=profile.level,
                    states=names,
                    direction=self._direction(candidates.origin.xy, candidate.xy),
                    distance=self._distance(candidate.distance_squared_meters),
                )
            )
        truncated = candidates.candidate_limit_reached or (
            len(visible) > candidates.visible_limit
        )
        visible = visible[: candidates.visible_limit]
        start = (page - 1) * candidates.page_size
        if page > 1 and start >= len(visible):
            raise NearbyPageError(self.copy().missing_page)
        stop = start + candidates.page_size
        current = self._world.locate(LocationQuery(xy=candidates.origin.xy))
        local = (
            self._companion.local_cultivators(
                current.location_name,
                exclude_companion_ids=(active.companion_id,) if active else (),
            )
            if page == 1
            and candidates.origin.space_type == "地表"
            and current.companion_pool
            else ()
        )
        return NearbyCultivatorPage(
            local_cultivators=local,
            active_companion=(
                self._active_summary(active.companion_id)
                if active is not None and page == 1
                else None
            ),
            cultivators=tuple(visible[start:stop]),
            page=page,
            page_size=candidates.page_size,
            has_next=stop < len(visible),
            truncated=truncated,
            visible_count=len(visible),
            space_type=candidates.origin.space_type,
        )

    def _active_summary(self, companion_id: str) -> LocalCultivator:
        definition = self._companion.definition(companion_id)
        return LocalCultivator(
            definition.companion_id,
            definition.name,
            definition.gender,
            definition.title,
            definition.description,
            definition.realm_id,
            definition.realm_name,
            definition.level,
            definition.interactable,
        )

    async def inspect_companion(self, user_id: str, companion_id: str) -> CompanionView | None:
        """按道侣编号取「我」名下的实例视图；没有实例就是没结交。

        实例的读法本身就带鉴权：它拿的是我的 user_id，问别人的道侣自然没有实例。
        """

        try:
            instance = await self._companion.instance(user_id, companion_id)
        except CompanionError:
            return None
        if instance is None:
            return None
        definition = self._companion.definition(companion_id)
        return CompanionView(
            companion_id=companion_id,
            name=definition.name,
            realm_name=definition.realm_name,
            level=instance.level,
            experience=instance.experience,
            attributes=instance.attributes,
            resources=instance.resources,
            weapon_name=instance.weapon_name,
            weapon_level=instance.weapon_level,
        )

    async def inspect_cultivator(self, user_id: str, query: str) -> CharacterPublicProfile | None:
        """按名字或用户编号在「附近」范围内解析一个人，取公开摘要。"""

        """只认附近可见的人：名字由附近的来往修士与本地修士共同解析，
        再向角色核心要公开摘要（它只回姓名、性别、境界、等级，不碰背包与修行槽）。"""
        wanted = str(query or "").strip()
        if not wanted:
            return None
        page = await self.nearby_cultivators(user_id, 1)
        target = ""
        for view in page.cultivators:
            if wanted in (view.name, view.user_id):
                target = view.user_id
                break
        if not target:
            return None
        profiles = await self._character.public_profiles((target,))
        return profiles[0] if profiles else None

    async def nearby_locations(self, user_id: str) -> NearbyWorldLocations:
        self._require_initialized()
        current = await self._location.current(user_id)
        if current.space_type != "地表":
            return NearbyWorldLocations(())
        map_view = self._world.map_view()
        origin_altitude = self._world.locate(LocationQuery(xy=current.xy)).altitude
        radius_squared = self._location_radius_meters**2
        values: list[tuple[int, object]] = []
        for location in map_view.locations:
            if location.xy == current.xy:
                continue
            dx = location.xy[0] - current.xy[0]
            dy = location.xy[1] - current.xy[1]
            horizontal_squared = (dx * dx + dy * dy) * map_view.cell_size_meters**2
            distance_squared = (
                horizontal_squared + (location.altitude - origin_altitude) ** 2
            )
            if distance_squared <= radius_squared:
                values.append((distance_squared, location))
        values.sort(key=lambda entry: (entry[0], entry[1].xy, entry[1].name))
        return NearbyWorldLocations(
            tuple(
                NearbyWorldLocation(
                    name=location.name,
                    region=location.region,
                    terrain=location.terrain,
                    functions=self._visible_functions(location.available_functions),
                    direction=self._direction(current.xy, location.xy),
                    distance=self._distance(distance_squared),
                )
                for distance_squared, location in values[: self._location_limit]
            )
        )

    def _direction(self, origin: tuple[int, int], target: tuple[int, int]) -> str:
        offset = (_sign(target[0] - origin[0]), _sign(target[1] - origin[1]))
        if offset == (0, 0):
            return ""
        return self._directions[offset]

    def _distance(self, distance_squared_meters: int) -> str:
        if distance_squared_meters == 0:
            return self._same_place
        distance_meters = math.sqrt(distance_squared_meters)
        distance_li = distance_meters / self._meters_per_li
        rounded = max(
            self._rounding_step,
            int(distance_li / self._rounding_step + 0.5) * self._rounding_step,
        )
        return f"约{rounded}里"

    def _visible_location(self, location: LocationView) -> LocationView:
        return replace(
            location,
            available_functions=self._visible_functions(location.available_functions),
        )

    def _validate_function_buttons(self, button_functions: frozenset[str]) -> None:
        """地点功能必须各有且只有一行按钮；缺按钮的功能不能静默消失。"""

        raw = self._data.dataset("世界字段定义").get("地点功能")
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise JsonDataError("世界字段定义.地点功能 必须是字典列表")
        names: list[str] = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise JsonDataError("世界字段定义.地点功能 只能包含对象")
            name = str(item.get("名称") or "").strip()
            if not name:
                raise JsonDataError("世界字段定义.地点功能 的名称不能为空")
            names.append(name)
        functions = set(names)
        missing = sorted(functions - set(button_functions))
        unknown = sorted(set(button_functions) - functions)
        if missing:
            raise JsonDataError(f"地点功能缺少位置按钮：{missing}")
        if unknown:
            raise JsonDataError(f"位置按钮引用了未登记地点功能：{unknown}")

    def _visible_functions(self, functions: Sequence[str]) -> tuple[str, ...]:
        return tuple(value for value in functions if value in self._open_functions)

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("位置查看玩法微服务尚未初始化")

    def _actions_for(
        self, page: str, *, surface: bool = True
    ) -> tuple[PositionAction, ...]:
        return tuple(
            render_action(template, {})
            for template in self._buttons
            if template.page == page
            and (
                not template.condition
                or (template.condition == "地表" and surface)
            )
        )

    def _location_entry_actions(
        self, locations: Sequence[NearbyWorldLocation]
    ) -> tuple[PositionAction, ...]:
        result: list[PositionAction] = []
        entry_templates = tuple(
            template for template in self._buttons if template.page == "地点条目"
        )
        for index, location in enumerate(locations, start=1):
            for template in entry_templates:
                action = render_action(template, {"地点": location.name})
                result.append(
                    PositionAction(
                        action_id=f"{action.action_id}.{index}",
                        label=action.label,
                        command=action.command,
                        behavior=action.behavior,
                        style=action.style,
                    )
                )
        return tuple(result)


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


__all__ = ["PositionFeature"]
