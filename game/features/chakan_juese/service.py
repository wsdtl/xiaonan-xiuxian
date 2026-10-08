"""查看角色流程编排。"""

from __future__ import annotations

from game.core.character import (
    CharacterNotFoundError,
    CharacterService,
    CharacterStateError,
)
from game.core.hosting import HostingError, HostingService
from game.core.injury import PLAYER_KEY, InjuryService
from game.core.innate_treasure import InnateTreasureService
from game.core.location import LocationMissingError, LocationService
from game.core.player_state import PlayerStateService
from game.core.world import LocationQuery, WorldService

from .contracts import (
    CharacterOverviewError,
    CharacterOverviewMissingError,
    CharacterOverviewResult,
)


class CharacterOverviewFeature:
    """组合角色资产、位置与当前玩家状态。"""

    def __init__(
        self,
        character: CharacterService,
        player_state: PlayerStateService,
        world: WorldService,
        location: LocationService,
        injury: InjuryService,
        innate_treasure: InnateTreasureService,
        hosting: HostingService,
    ) -> None:
        self._character = character
        self._player_state = player_state
        self._world = world
        self._location = location
        self._injury = injury
        self._innate_treasure = innate_treasure
        self._hosting = hosting
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("查看角色玩法微服务已经初始化")
        if not self._character.status().initialized:
            raise RuntimeError("角色核心微服务必须先于查看角色玩法启动")
        if not self._player_state.status().initialized:
            raise RuntimeError("玩家状态微服务必须先于查看角色玩法启动")
        if not self._world.status().initialized:
            raise RuntimeError("世界地点微服务必须先于查看角色玩法启动")
        if not self._location.status().initialized:
            raise RuntimeError("玩家位置微服务必须先于查看角色玩法启动")
        if not self._injury.status().initialized:
            raise RuntimeError("长期伤势核心必须先于查看角色玩法启动")
        if not self._innate_treasure.status().initialized:
            raise RuntimeError("先天灵宝核心必须先于查看角色玩法启动")
        if not self._hosting.status().initialized:
            raise RuntimeError("托管核心必须先于查看角色玩法启动")
        self._initialized = True

    async def inspect(self, user_id: str) -> CharacterOverviewResult:
        if not self._initialized:
            raise RuntimeError("查看角色玩法微服务尚未初始化")
        try:
            character = await self._character.profile(user_id)
        except CharacterNotFoundError as exc:
            raise CharacterOverviewMissingError(str(exc)) from exc
        except CharacterStateError as exc:
            raise CharacterOverviewError(str(exc)) from exc
        state = await self._player_state.current(user_id)
        if state is None:
            raise CharacterOverviewError("人物缺少玩家状态")
        try:
            player_location = await self._location.current(user_id)
        except LocationMissingError as exc:
            raise CharacterOverviewError(str(exc)) from exc
        location = self._world.locate(LocationQuery(xy=player_location.xy))
        equipped_counts = {
            category: sum(
                content.category == category for content in character.equipped_content
            )
            for category, _ in character.cultivation_slots
        }
        injuries = self._injury.summary(await self._injury.state(user_id, PLAYER_KEY))
        treasure_status = self._innate_treasure.status()
        active_treasure = await self._innate_treasure.active(user_id)
        try:
            hosting = await self._hosting.current(user_id)
        except HostingError as exc:
            raise CharacterOverviewError(str(exc)) from exc
        return CharacterOverviewResult(
            character=character,
            attribute_baselines=self._character.attribute_baselines(),
            xy=player_location.xy,
            location_name=location.location_name,
            region=location.region,
            terrain=location.terrain,
            altitude=location.altitude,
            states=tuple(
                (
                    state_type,
                    "托管暂停"
                    if state_type == "控制"
                    and slot.name == "托管中"
                    and hosting is not None
                    and hosting.status == "已暂停"
                    else slot.name,
                )
                for state_type, slot in state.states.items()
            ),
            cultivation_usage=tuple(
                (category, equipped_counts[category], total)
                for category, total in character.cultivation_slots
            ),
            injuries=tuple(
                (str(value["名称"]), int(value["层数"])) for value in injuries.entries
            ),
            innate_treasure=active_treasure,
            innate_treasure_usage=(
                1 if active_treasure is not None else 0,
                treasure_status.slot_count,
            ),
        )


__all__ = ["CharacterOverviewFeature"]
