"""世界功能对外公开的数据契约。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorldStatus:
    initialized: bool
    location_count: int
    region_count: int
    road_count: int
    terrain_cell_count: int
    journey_realm_count: int


@dataclass(frozen=True)
class LocationQuery:
    location_name: str = ""
    xy: tuple[int, int] | None = None


@dataclass(frozen=True)
class LocationView:
    location_key: str
    location_name: str
    xy: tuple[int, int]
    region: str
    terrain: str
    environment_id: str
    altitude: int
    available_functions: tuple[str, ...]
    plant_pool: tuple[str, ...]
    mineral_pool: tuple[str, ...]
    companion_pool: tuple[str, ...]
    enemy_pool: tuple[str, ...]
    enemy_multiplier: tuple[int, ...]


@dataclass(frozen=True)
class JourneyQuery:
    origin_xy: tuple[int, int]
    destination: LocationQuery
    realm_id: str


@dataclass(frozen=True)
class JourneyMetrics:
    horizontal_distance_m: int
    road_segment_count: int
    terrain_segment_count: int
    minimum_altitude_m: int
    maximum_altitude_m: int
    total_ascent_m: int
    total_descent_m: int
    maximum_step_ascent_m: int
    maximum_step_descent_m: int
    maximum_uphill_permille: int
    maximum_downhill_permille: int
    weighted_distance_m: int


@dataclass(frozen=True)
class JourneyPassageSegment:
    kind: str
    name: str
    start_xy: tuple[int, int]
    end_xy: tuple[int, int]
    direction: tuple[int, int]
    horizontal_distance_m: int


@dataclass(frozen=True)
class JourneyPlan:
    origin: LocationView
    destination: LocationView
    realm_id: str
    realm_name: str
    travel_method: str
    route: tuple[tuple[int, int], ...]
    passages: tuple[JourneyPassageSegment, ...]
    via_locations: tuple[str, ...]
    metrics: JourneyMetrics
    narrative: tuple[str, ...]


@dataclass(frozen=True)
class MapCoordinateBand:
    y: int
    x_ranges: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class MapTerrainZone:
    name: str
    terrain: str
    bounds: tuple[int, int, int, int]
    label_xy: tuple[int, int]
    cell_count: int
    coordinate_bands: tuple[MapCoordinateBand, ...]


@dataclass(frozen=True)
class MapRegion:
    name: str
    category: str
    description: str
    bounds: tuple[int, int, int, int]
    label_xy: tuple[int, int]
    cell_count: int
    altitude_range: tuple[int, int]
    coordinate_bands: tuple[MapCoordinateBand, ...]
    terrain_zones: tuple[str, ...]


@dataclass(frozen=True)
class MapLocation:
    key: str
    name: str
    description: str
    xy: tuple[int, int]
    region: str
    terrain: str
    altitude: int
    available_functions: tuple[str, ...]


@dataclass(frozen=True)
class MapRoad:
    road_type: str
    start_key: str
    end_key: str
    start: str
    end: str
    coordinates: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class WorldMapView:
    schema: str
    version: int
    name: str
    description: str
    birthplace_key: str
    birthplace: str
    bounds: tuple[int, int, int, int]
    cell_size_meters: int
    altitude_range: tuple[int, int]
    surface: tuple[tuple[int, ...], ...]
    regions: tuple[MapRegion, ...]
    terrain_zones: tuple[MapTerrainZone, ...]
    locations: tuple[MapLocation, ...]
    roads: tuple[MapRoad, ...]


__all__ = [
    "JourneyMetrics",
    "JourneyPassageSegment",
    "JourneyPlan",
    "JourneyQuery",
    "LocationQuery",
    "LocationView",
    "MapCoordinateBand",
    "MapLocation",
    "MapRegion",
    "MapRoad",
    "MapTerrainZone",
    "WorldMapView",
    "WorldStatus",
]
