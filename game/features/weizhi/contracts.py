"""位置查看玩法微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.companion import LocalCultivator
from game.core.world import LocationView


class PositionViewError(RuntimeError):
    """位置查看无法完成。"""


class NearbyPageError(PositionViewError, ValueError):
    """附近查询页码无效。"""


@dataclass(frozen=True)
class PositionCopy:
    error_icon: str
    location_icon: str
    cultivator_icon: str
    navigation_icon: str
    page_icon: str
    unknown_location: str
    coordinate: str
    altitude: str
    cultivator_summary: str
    cultivator_direction: str
    colocated_cultivator_direction: str
    location_summary: str
    location_detail: str
    state_prefix: str
    state_separator: str
    team_state: str
    sect_follow_leader_state: str
    sect_follow_member_state: str
    fellowship_conflict_state: str
    function_separator: str
    no_available_function: str
    current_place_section: str
    region_label: str
    terrain_label: str
    coordinate_label: str
    altitude_label: str
    local_cultivators_section: str
    active_companion_section: str
    count_label: str
    overview_title: str
    overview_cultivators_section: str
    overview_local_label: str
    overview_visiting_label: str
    overview_nearby_label: str
    overview_locations_section: str
    overview_no_locations: str
    overview_current_section: str
    overview_current_label: str
    cultivators_title: str
    cultivators_local_section: str
    cultivators_active_section: str
    cultivators_visiting_section: str
    cultivators_inside_section: str
    cultivators_empty: str
    cultivators_page_section: str
    cultivators_current_label: str
    cultivators_truncated: str
    invalid_page: str
    missing_page: str
    locations_title: str
    locations_section: str
    locations_empty: str
    invalid_command: str


@dataclass(frozen=True)
class PositionAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class CurrentPositionView:
    location: LocationView
    local_cultivators: tuple[LocalCultivator, ...]
    active_companion: LocalCultivator | None
    space_type: str = "地表"
    space_name: str = ""


@dataclass(frozen=True)
class NearbyCultivatorView:
    user_id: str
    name: str
    gender: str
    realm_name: str
    level: int
    states: tuple[str, ...]
    direction: str
    distance: str


@dataclass(frozen=True)
class NearbyCultivatorPage:
    local_cultivators: tuple[LocalCultivator, ...]
    active_companion: LocalCultivator | None
    cultivators: tuple[NearbyCultivatorView, ...]
    page: int
    page_size: int
    has_next: bool
    truncated: bool
    visible_count: int
    space_type: str = "地表"


@dataclass(frozen=True)
class NearbyWorldLocation:
    name: str
    region: str
    terrain: str
    functions: tuple[str, ...]
    direction: str
    distance: str


@dataclass(frozen=True)
class NearbyWorldLocations:
    values: tuple[NearbyWorldLocation, ...]


@dataclass(frozen=True)
class NearbyOverview:
    current: CurrentPositionView
    visiting_cultivator_count: int
    locations: tuple[NearbyWorldLocation, ...]


__all__ = [
    "CurrentPositionView",
    "NearbyCultivatorPage",
    "NearbyCultivatorView",
    "NearbyOverview",
    "NearbyPageError",
    "NearbyWorldLocation",
    "NearbyWorldLocations",
    "PositionAction",
    "PositionCopy",
    "PositionViewError",
]
