"""无功能地点发起闭关/探险前的自动寻路。"""
from __future__ import annotations

from game.core.action_group import ActionGroupService
from game.core.character import CharacterService
from game.core.data import JsonDataError, JsonDataService
from game.core.location import (
    GroupLocationMoveCommand,
    LocationConflictError,
    LocationService,
)
from game.core.player_state import PlayerStateService
from game.core.world import JourneyQuery, LocationQuery, WorldService


class AutoTravelError(RuntimeError):
    """自动寻路无法完成。"""


class AutoTravelService:
    """找最近可用地点并整队移动；只做移动，不开始玩法。"""

    def __init__(
        self,
        data: JsonDataService,
        world: WorldService,
        location: LocationService,
        character: CharacterService,
        player_state: PlayerStateService,
        action_group: ActionGroupService,
    ) -> None:
        self._data = data
        self._world = world
        self._location = location
        self._character = character
        self._player_state = player_state
        self._action_group = action_group

    async def ensure_at_function(
        self,
        user_id: str,
        function: str,
        request_id: str,
        guard: str,
    ) -> str:
        """当前位置有该功能就返回空串；否则整队移到最近可用地点并返回地点名。"""

        current = await self._location.current(user_id)
        here = self._world.locate(LocationQuery(xy=current.xy))
        if function in here.available_functions:
            return ""
        if current.space_type != "地表":
            raise AutoTravelError("当前身处特殊空间，不能自动寻路")

        participants = await self._action_group.participants(user_id)
        locations = [await self._location.current(value) for value in participants]
        origin = (current.space_type, current.space_id, current.xy)
        if any(
            (value.space_type, value.space_id, value.xy) != origin
            for value in locations
        ):
            raise AutoTravelError("同行修士不在同一地点，不能自动寻路")

        names = {
            value.user_id: value.name
            for value in await self._character.public_profiles(participants)
        }
        for value in participants:
            check = await self._player_state.authorize(value, guard)
            if not check.allowed:
                name = names.get(value, "有参与修士")
                raise AutoTravelError(f"{name}当前不能{function}：{check.reason}")

        profile = await self._character.profile(user_id)
        best: tuple[int, str, object] | None = None
        for name in self._data.entities("地点"):
            target = self._world.locate(LocationQuery(location_name=name))
            if function not in target.available_functions:
                continue
            try:
                plan = self._world.plan_journey(
                    JourneyQuery(
                        origin_xy=current.xy,
                        destination=LocationQuery(location_name=name),
                        realm_id=profile.realm_id,
                    )
                )
            except (JsonDataError, ValueError):
                continue
            key = (int(plan.metrics.weighted_distance_m), name)
            if best is None or key < (best[0], best[1]):
                best = (key[0], key[1], target)
        if best is None:
            raise AutoTravelError(f"附近没有可用的{function}地点")

        target = best[2]
        try:
            await self._location.move_many(
                GroupLocationMoveCommand(
                    owner_user_id=user_id,
                    request_id=f"{request_id}:travel",
                    participant_user_ids=participants,
                    expected_origin_xy=current.xy,
                    destination_xy=target.xy,
                )
            )
        except LocationConflictError as exc:
            raise AutoTravelError("同行位置刚刚发生变化，请重试") from exc
        return target.location_name
