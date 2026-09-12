"""由正式世界 JSON 驱动的地点查询服务。"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from itertools import pairwise

from game.core.data import JsonDataError, JsonDataService, positive_int as _positive_int

from .contracts import (
    JourneyPlan,
    JourneyQuery,
    LocationQuery,
    LocationView,
    MapCoordinateBand,
    MapLocation,
    MapRegion,
    MapRoad,
    MapTerrainZone,
    WorldMapView,
    WorldStatus,
)
from .journey import JourneyPlanner

_LOCATION_FIELDS = frozenset({"坐标", "说明", "可用功能", "功能配置", "单次遭遇敌人倍率"})
_REGION_FIELDS = frozenset({"类别", "坐标带", "说明"})
_TERRAIN_ZONE_FIELDS = frozenset({"名称", "地形", "坐标带"})


class WorldService:
    """解析地点、区域、地形和地表海拔，不持有玩家位置。"""

    def __init__(self, data: JsonDataService) -> None:
        self._data = data
        self._initialized = False
        self._locations: Mapping[str, Mapping[str, object]] = {}
        self._regions: Mapping[str, Mapping[str, object]] = {}
        self._region_cells: dict[str, frozenset[tuple[int, int]]] = {}
        self._region_by_xy: dict[tuple[int, int], str] = {}
        self._terrain_zones: dict[str, tuple[str, frozenset[tuple[int, int]]]] = {}
        self._terrain_by_xy: dict[tuple[int, int], tuple[str, str]] = {}
        self._environment_by_terrain: dict[str, str] = {}
        self._location_regions: dict[str, str] = {}
        self._locations_by_xy: dict[
            tuple[int, int], tuple[str, Mapping[str, object]]
        ] = {}
        self._feature_contents: dict[str, tuple[str, ...]] = {}
        self._feature_config_functions: frozenset[str] = frozenset()
        self._feature_requirements: dict[
            str, tuple[tuple[str, ...], tuple[str, ...]]
        ] = {}
        self._surface: tuple[tuple[int, ...], ...] = ()
        self._bounds: tuple[int, int, int, int] = (0, 0, 0, 0)
        self._roads: tuple[MapRoad, ...] = ()
        self._map_view: WorldMapView | None = None
        self._journey: JourneyPlanner | None = None

    def initialize(self) -> WorldStatus:
        if self._initialized:
            raise RuntimeError("世界地点服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据服务必须先于世界地点服务启动")

        worlds = self._data.entities("世界")
        if len(worlds) != 1:
            raise JsonDataError(f"当前世界地图必须且只能定义一个世界：{tuple(worlds)}")
        world_name, world = next(iter(worlds.items()))
        self._locations = self._data.entities("地点")
        self._regions = self._data.entities("区域")
        terrain = self._data.dataset("地势").get("地势")
        if not isinstance(terrain, Mapping):
            raise JsonDataError("地势数据必须是对象")
        self._surface = _surface_grid(terrain.get("地表高度"))
        self._bounds = _xy_bounds(terrain.get("坐标边界"))
        cell_size_meters = _positive_int(
            terrain.get("水平每格米数"),
            "地势.水平每格米数",
        )
        altitude_range = _axis_range(terrain.get("海拔范围"), "地势.海拔范围")
        if len(self._surface) != self._bounds[3] - self._bounds[2] + 1:
            raise JsonDataError("地势地表高度的 y 轴尺寸与坐标边界不一致")
        if any(
            len(row) != self._bounds[1] - self._bounds[0] + 1 for row in self._surface
        ):
            raise JsonDataError("地势地表高度的 x 轴尺寸与坐标边界不一致")
        surface_range = (
            min(min(row) for row in self._surface),
            max(max(row) for row in self._surface),
        )
        if altitude_range != surface_range:
            raise JsonDataError(
                f"地势.海拔范围与地表高度不一致：{altitude_range} != {surface_range}"
            )

        self._load_region_domains()
        self._load_terrain_domains()
        self._environment_by_terrain = _environment_ids(self._data)
        missing_environments = {
            terrain
            for _, terrain in self._terrain_by_xy.values()
            if terrain not in self._environment_by_terrain
        }
        if missing_environments:
            raise JsonDataError(
                "地形缺少同名战场环境：" + "、".join(sorted(missing_environments))
            )
        definitions = self._data.dataset("世界定义").get("地点功能")
        (
            self._feature_contents,
            self._feature_requirements,
            self._feature_config_functions,
        ) = _feature_definitions(
            definitions
        )
        for location_key, raw in self._locations.items():
            _validate_location_data(
                raw,
                location_key,
                self._feature_requirements,
                self._feature_config_functions,
            )
        self._location_regions = {}
        self._locations_by_xy = {}
        for location_name, raw in self._locations.items():
            xy = _xy(raw.get("坐标"), f"地点 {location_name}.坐标")
            if xy in self._locations_by_xy:
                raise JsonDataError(f"地点坐标重复：{xy}")
            directory_region = self._data.entity_record(
                "地点", location_name
            ).directory_owner
            coordinate_region = self._region_at(xy)
            if directory_region != coordinate_region:
                raise JsonDataError(
                    f"地点 {location_name} 的目录区域与坐标区域不一致："
                    f"{directory_region or '<空>'} != {coordinate_region}"
                )
            self._location_regions[location_name] = directory_region
            self._locations_by_xy[xy] = (location_name, raw)
        for location_name, raw in self._locations.items():
            xy = _xy(raw.get("坐标"), f"地点 {location_name}.坐标")
            terrain_name = self._terrain_at(xy)
            self._require_pool(f"灵植-{terrain_name}", "基础物品")
            self._require_pool(f"灵矿-{terrain_name}", "基础物品")
            for function in _strings(raw.get("可用功能")):
                sections = self._feature_contents.get(function)
                if sections is None:
                    raise JsonDataError(
                        f"地点 {location_name} 使用未登记功能：{function}"
                    )
                for section in sections:
                    if section == "商店":
                        self._require_location_shop(location_name)
                    elif section in {
                        "炼器工匠", "炼丹师", "阵师", "讨伐", "讨伐首领",
                        "讨伐辅助", "讨伐属从",
                    }:
                        self._require_location_entity(location_name, section)
                    else:
                        self._require_location_pool(location_name, section)
        birthplace = str(world.get("出生地") or "").strip()
        if birthplace not in self._locations:
            raise JsonDataError(f"世界出生地不存在：{birthplace or '<空>'}")
        self._roads = self._map_roads(world)
        self._map_view = WorldMapView(
            schema="game.world_map.presentation",
            version=2,
            name=world_name,
            description=str(world.get("说明") or "").strip(),
            birthplace_key=birthplace,
            birthplace=birthplace,
            bounds=self._bounds,
            cell_size_meters=cell_size_meters,
            altitude_range=altitude_range,
            surface=self._surface,
            regions=self._map_regions(),
            terrain_zones=self._map_terrain_zones(),
            locations=self._map_locations(),
            roads=self._roads,
        )
        self._journey = JourneyPlanner(
            self._data,
            bounds=self._bounds,
            cell_size_meters=cell_size_meters,
            surface=self._surface,
            region_by_xy=self._region_by_xy,
            terrain_by_xy=self._terrain_by_xy,
            location_name_by_xy={
                xy: value[0] for xy, value in self._locations_by_xy.items()
            },
            roads=self._roads,
        )
        self._initialized = True
        return self.status()

    def status(self) -> WorldStatus:
        return WorldStatus(
            initialized=self._initialized,
            location_count=len(self._locations),
            region_count=len(self._regions),
            road_count=len(self._roads),
            terrain_cell_count=sum(len(row) for row in self._surface),
            journey_realm_count=(self._journey.realm_count if self._journey else 0),
        )

    def map_view(self) -> WorldMapView:
        """返回 Web 等展示层可直接使用的完整只读地图快照。"""

        self._require_initialized()
        if self._map_view is None:
            raise RuntimeError("世界地图快照尚未构建")
        return self._map_view

    def feature_config(self, function: str) -> Mapping[str, object]:
        """返回唯一地点专属功能的配置；功能归属由地点目录决定。"""

        self._require_initialized()
        name = str(function or "").strip()
        if not name:
            raise ValueError("地点功能不能为空")
        owners = [
            location_name
            for location_name, raw in self._locations.items()
            if name in _strings(raw.get("可用功能"))
        ]
        if len(owners) != 1:
            raise JsonDataError(
                f"地点专属功能 {name} 必须且只能有一个地点：{tuple(owners)}"
            )
        raw = self._locations[owners[0]]
        configs = raw.get("功能配置")
        if not isinstance(configs, Mapping):
            raise JsonDataError(f"地点 {owners[0]} 缺少功能配置：{name}")
        config = configs.get(name)
        if not isinstance(config, Mapping):
            raise JsonDataError(f"地点 {owners[0]}.功能配置.{name} 必须是对象")
        return config

    def locate(self, query: LocationQuery) -> LocationView:
        self._require_initialized()
        location_name = str(query.location_name or "").strip()
        if bool(location_name) == (query.xy is not None):
            raise ValueError("地点查询必须只提供地点名或 xy")
        if location_name:
            location_key = location_name
            raw = self._locations.get(location_key)
            if raw is None:
                raise JsonDataError(f"地点不存在：{location_name}")
            xy = _xy(raw.get("坐标"), f"地点 {location_name}.坐标")
            region = self._location_regions[location_key]
        else:
            xy = _validate_xy(query.xy, self._bounds)
            location = self._location_at(xy)
            location_key, raw = location if location is not None else ("", {})
            region = (
                self._location_regions[location_key]
                if location_key
                else self._region_at(xy)
            )
        terrain = self._terrain_at(xy)
        functions = _strings(raw.get("可用功能"))
        content_sections = {
            section
            for function in functions
            for section in self._feature_contents[function]
        }
        plant_pool = (f"灵植-{terrain}",)
        mineral_pool = (f"灵矿-{terrain}",)
        companion_pool = (
            (f"{location_key}道侣",)
            if location_key and "道侣" in content_sections
            else ()
        )
        enemy_pool = (
            (f"{location_key}敌人",)
            if location_key and "敌人" in content_sections
            else ()
        )
        return LocationView(
            location_key=location_key,
            location_name=location_key,
            xy=xy,
            region=region,
            terrain=terrain,
            environment_id=self._environment_by_terrain[terrain],
            altitude=self._altitude(xy),
            available_functions=functions,
            plant_pool=plant_pool,
            mineral_pool=mineral_pool,
            companion_pool=companion_pool,
            enemy_pool=enemy_pool,
            enemy_multiplier=_numbers(raw.get("单次遭遇敌人倍率")),
        )

    def plan_journey(self, query: JourneyQuery) -> JourneyPlan:
        """按正式路网、地形、高度和境界叙事规划一次即时行程。"""

        self._require_initialized()
        if self._journey is None:
            raise RuntimeError("世界行路规划器尚未构建")
        origin = self.locate(LocationQuery(xy=query.origin_xy))
        destination = self.locate(query.destination)
        return self._journey.plan(
            origin=origin,
            destination=destination,
            realm_id=query.realm_id,
        )

    def _map_regions(self) -> tuple[MapRegion, ...]:
        regions: list[MapRegion] = []
        for region_name, raw in self._regions.items():
            cells = self._region_cells[region_name]
            terrain_zones = tuple(
                sorted(
                    zone_name
                    for zone_name, (_, zone_cells) in self._terrain_zones.items()
                    if not cells.isdisjoint(zone_cells)
                )
            )
            regions.append(
                MapRegion(
                    name=region_name,
                    category=str(raw.get("类别") or "").strip(),
                    description=str(raw.get("说明") or "").strip(),
                    bounds=_cell_bounds(cells),
                    label_xy=_label_cell(cells),
                    cell_count=len(cells),
                    coordinate_bands=_map_coordinate_bands(cells),
                    terrain_zones=terrain_zones,
                )
            )
        return tuple(
            sorted(
                regions,
                key=lambda item: (item.bounds[2], item.bounds[0], item.name),
            )
        )

    def _map_terrain_zones(self) -> tuple[MapTerrainZone, ...]:
        return tuple(
            MapTerrainZone(
                name=name,
                terrain=terrain,
                bounds=_cell_bounds(cells),
                label_xy=_label_cell(cells),
                cell_count=len(cells),
                coordinate_bands=_map_coordinate_bands(cells),
            )
            for name, (terrain, cells) in sorted(self._terrain_zones.items())
        )

    def _map_locations(self) -> tuple[MapLocation, ...]:
        locations: list[MapLocation] = []
        for location_name, raw in self._locations.items():
            xy = _xy(raw.get("坐标"), f"地点 {location_name}.坐标")
            region = self._location_regions[location_name]
            locations.append(
                MapLocation(
                    key=location_name,
                    name=location_name,
                    description=str(raw.get("说明") or "").strip(),
                    xy=xy,
                    region=region,
                    terrain=self._terrain_at(xy),
                    altitude=self._altitude(xy),
                    available_functions=_strings(raw.get("可用功能")),
                )
            )
        return tuple(
            sorted(locations, key=lambda item: (item.xy[1], item.xy[0], item.name))
        )

    def _map_roads(self, world: Mapping[str, object]) -> tuple[MapRoad, ...]:
        road_documents = self._data.dataset("道路")
        road_types = _strings(world.get("道路"))
        if not road_types:
            raise JsonDataError("世界必须引用至少一种道路")
        unknown = set(road_types) - set(road_documents)
        if unknown:
            raise JsonDataError(f"世界引用不存在的道路：{'、'.join(sorted(unknown))}")
        roads: list[MapRoad] = []
        for road_type in road_types:
            values = road_documents[road_type]
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                raise JsonDataError(f"道路文件必须是字典列表：{road_type}")
            for index, raw in enumerate(values):
                if not isinstance(raw, Mapping):
                    raise JsonDataError(f"道路必须是对象：{road_type}[{index}]")
                start = str(raw.get("起点") or "").strip()
                end = str(raw.get("终点") or "").strip()
                if start not in self._locations or end not in self._locations:
                    raise JsonDataError(
                        f"道路端点不存在：{road_type}[{index}] {start or '<空>'} -> {end or '<空>'}"
                    )
                coordinates = _coordinates(
                    raw.get("途经坐标"),
                    f"道路 {road_type}[{index}].途经坐标",
                    self._bounds,
                )
                start_xy = _xy(self._locations[start].get("坐标"), f"地点 {start}.坐标")
                end_xy = _xy(self._locations[end].get("坐标"), f"地点 {end}.坐标")
                if coordinates[0] != start_xy or coordinates[-1] != end_xy:
                    raise JsonDataError(
                        f"道路坐标端点与地点不一致：{road_type}[{index}] {start} -> {end}"
                    )
                crossed_locations = {
                    self._locations_by_xy[xy][0]
                    for xy in coordinates[1:-1]
                    if xy in self._locations_by_xy
                }
                if crossed_locations:
                    raise JsonDataError(
                        f"道路中段穿过非端点地点：{road_type}[{index}] "
                        f"{start} -> {end} -> {'、'.join(sorted(crossed_locations))}"
                    )
                roads.append(
                    MapRoad(
                        road_type=road_type,
                        start_key=start,
                        end_key=end,
                        start=start,
                        end=end,
                        coordinates=coordinates,
                    )
                )
        return tuple(roads)

    def _location_at(
        self, xy: tuple[int, int]
    ) -> tuple[str, Mapping[str, object]] | None:
        return self._locations_by_xy.get(xy)

    def _require_pool(self, file_id: str, section: str) -> None:
        try:
            self._data.pool_members((file_id,), section)
        except JsonDataError as exc:
            raise JsonDataError(f"派生资源池无效：{file_id} -> {section}") from exc

    def _require_location_pool(self, location_name: str, section: str) -> None:
        file_id = f"{location_name}{section}"
        try:
            members = self._data.pool_members((file_id,), section)
        except JsonDataError as exc:
            raise JsonDataError(f"派生资源池无效：{file_id} -> {section}") from exc
        misplaced = tuple(
            member
            for member in members
            if self._data.entity_record(section, member).directory_owner
            != location_name
        )
        if misplaced:
            raise JsonDataError(
                f"地点资源池不在对应目录：{file_id} -> {'、'.join(misplaced)}"
            )

    def _require_location_shop(self, location_name: str) -> None:
        file_id = f"{location_name}商店"
        shop = self._data.entities("地点商店").get(file_id)
        if shop is None:
            raise JsonDataError(f"交易地点缺少同目录商店：{location_name}")
        owner = self._data.entity_record("地点商店", file_id).directory_owner
        if owner != location_name:
            raise JsonDataError(f"地点商店不在对应目录：{file_id} -> {owner}")

    def _require_location_entity(self, location_name: str, section: str) -> None:
        file_id = f"{location_name}{section}"
        values = self._data.entities(section)
        matches = [
            entity_id
            for entity_id in values
            if self._data.entity_record(section, entity_id).source_file == file_id
        ]
        if not matches:
            raise JsonDataError(f"地点缺少同目录内容：{file_id}.json")
        for entity_id in matches:
            owner = self._data.entity_record(section, entity_id).directory_owner
            if owner != location_name:
                raise JsonDataError(
                    f"地点内容不在对应目录：{file_id} -> {owner or '<空>'}"
                )
            if "地点" in values[entity_id]:
                raise JsonDataError(
                    f"地点内容重复保存地点字段：{file_id} -> {entity_id}"
                )

    def _region_at(self, xy: tuple[int, int]) -> str:
        try:
            return self._region_by_xy[xy]
        except KeyError as exc:
            raise JsonDataError(f"xy 不属于任何区域：{xy}") from exc

    def _altitude(self, xy: tuple[int, int]) -> int:
        x, y = xy
        return self._surface[y - self._bounds[2]][x - self._bounds[0]]

    def _terrain_at(self, xy: tuple[int, int]) -> str:
        try:
            return self._terrain_by_xy[xy][1]
        except KeyError as exc:
            raise JsonDataError(f"xy 不属于任何地形分区：{xy}") from exc

    def _load_region_domains(self) -> None:
        self._region_cells = {}
        self._region_by_xy = {}
        for region_name, raw in self._regions.items():
            unknown = set(raw) - _REGION_FIELDS
            if unknown:
                raise JsonDataError(
                    f"区域 {region_name} 存在未声明字段：{'、'.join(sorted(unknown))}"
                )
            category = raw.get("类别")
            description = raw.get("说明")
            if not isinstance(category, str) or not category.strip():
                raise JsonDataError(f"区域 {region_name}.类别必须是非空字符串")
            if not isinstance(description, str) or not description.strip():
                raise JsonDataError(f"区域 {region_name}.说明必须是非空字符串")
            cells = _coordinate_domain(
                raw.get("坐标带"),
                f"区域 {region_name}.坐标带",
                self._bounds,
            )
            if not _connected(cells):
                raise JsonDataError(f"区域坐标域必须连通：{region_name}")
            self._region_cells[region_name] = cells
            _register_cells(self._region_by_xy, cells, region_name, "区域")
        _require_full_coverage(self._region_by_xy, self._bounds, "区域")

    def _load_terrain_domains(self) -> None:
        values = self._data.dataset("地形分区").get("地形分区")
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise JsonDataError("地形分区必须是字典列表")
        self._terrain_zones = {}
        self._terrain_by_xy = {}
        for index, raw in enumerate(values):
            if not isinstance(raw, Mapping):
                raise JsonDataError(f"地形分区[{index}]必须是对象")
            unknown = set(raw) - _TERRAIN_ZONE_FIELDS
            if unknown:
                raise JsonDataError(
                    f"地形分区[{index}]存在未声明字段：{'、'.join(sorted(unknown))}"
                )
            name = str(raw.get("名称") or "").strip()
            terrain = str(raw.get("地形") or "").strip()
            if not name or not terrain or name in self._terrain_zones:
                raise JsonDataError(
                    f"地形分区[{index}]名称、地形不能为空且名称不能重复"
                )
            cells = _coordinate_domain(
                raw.get("坐标带"),
                f"地形分区 {name}.坐标带",
                self._bounds,
            )
            if not _connected(cells):
                raise JsonDataError(f"地形分区坐标域必须连通：{name}")
            self._terrain_zones[name] = (terrain, cells)
            for xy in cells:
                if xy in self._terrain_by_xy:
                    previous = self._terrain_by_xy[xy][0]
                    raise JsonDataError(f"地形分区重叠：{xy} -> {previous}、{name}")
                self._terrain_by_xy[xy] = (name, terrain)
        _require_full_coverage(self._terrain_by_xy, self._bounds, "地形分区")

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("世界地点服务尚未初始化")


def _surface_grid(value: object) -> tuple[tuple[int, ...], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise JsonDataError("地势.地表高度必须是非空二维数组")
    rows: list[tuple[int, ...]] = []
    for row in value:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or not row:
            raise JsonDataError("地势.地表高度必须是非空二维数组")
        if any(isinstance(item, bool) or not isinstance(item, int) for item in row):
            raise JsonDataError("地势.地表高度只能包含整数")
        rows.append(tuple(row))
    return tuple(rows)


def _xy_bounds(value: object) -> tuple[int, int, int, int]:
    x_axis, y_axis = _range_bounds(value, "地势.坐标边界")
    return (x_axis[0], x_axis[1], y_axis[0], y_axis[1])


def _range_bounds(
    value: object,
    label: str,
) -> tuple[tuple[int, int], tuple[int, int]]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return (
        _axis_range(value.get("x轴"), f"{label}.x轴"),
        _axis_range(value.get("y轴"), f"{label}.y轴"),
    )


def _axis_range(value: object, label: str) -> tuple[int, int]:
    if not _ordered_pair(value):
        raise JsonDataError(f"{label}必须是两个顺序整数")
    return (value[0], value[1])


def _coordinates(
    value: object,
    label: str,
    bounds: tuple[int, int, int, int],
) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise JsonDataError(f"{label}必须是非空二维坐标数组")
    coordinates = tuple(_validate_xy(item, bounds) for item in value)
    for previous, current in pairwise(coordinates):
        dx = abs(current[0] - previous[0])
        dy = abs(current[1] - previous[1])
        if (dx, dy) == (0, 0) or dx > 1 or dy > 1:
            raise JsonDataError(f"{label}存在不连续坐标：{previous} -> {current}")
    return coordinates


def _xy(value: object, label: str) -> tuple[int, int]:
    if not _valid_pair(value):
        raise JsonDataError(f"{label}必须是两个整数")
    return (value[0], value[1])


def _validate_xy(
    value: tuple[int, int] | None,
    bounds: tuple[int, int, int, int],
) -> tuple[int, int]:
    xy = _xy(value, "xy")
    if not (bounds[0] <= xy[0] <= bounds[1] and bounds[2] <= xy[1] <= bounds[3]):
        raise JsonDataError(f"xy 超出世界边界：{xy}")
    return xy


def _valid_pair(value: object) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
        and len(value) == 2
        and all(isinstance(item, int) and not isinstance(item, bool) for item in value)
    )


def _ordered_pair(value: object) -> bool:
    return _valid_pair(value) and value[0] <= value[1]


def _coordinate_domain(
    value: object,
    label: str,
    bounds: tuple[int, int, int, int],
) -> frozenset[tuple[int, int]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise JsonDataError(f"{label}必须是非空字典列表")
    cells: set[tuple[int, int]] = set()
    seen_y: set[int] = set()
    for index, band in enumerate(value):
        if not isinstance(band, Mapping) or set(band) != {"y", "x轴"}:
            raise JsonDataError(f"{label}[{index}]必须只包含 y 和 x轴")
        y = band.get("y")
        if (
            isinstance(y, bool)
            or not isinstance(y, int)
            or not bounds[2] <= y <= bounds[3]
            or y in seen_y
        ):
            raise JsonDataError(f"{label}[{index}].y 越界或重复")
        seen_y.add(y)
        x_ranges = band.get("x轴")
        if (
            not isinstance(x_ranges, Sequence)
            or isinstance(x_ranges, (str, bytes))
            or not x_ranges
        ):
            raise JsonDataError(f"{label}[{index}].x轴必须是非空范围列表")
        previous_end = bounds[0] - 1
        for range_index, x_range in enumerate(x_ranges):
            if (
                not _ordered_pair(x_range)
                or x_range[0] < bounds[0]
                or x_range[1] > bounds[1]
                or x_range[0] <= previous_end
            ):
                raise JsonDataError(
                    f"{label}[{index}].x轴[{range_index}]越界、重叠或未排序"
                )
            cells.update((x, y) for x in range(x_range[0], x_range[1] + 1))
            previous_end = x_range[1]
    return frozenset(cells)


def _register_cells(
    owners: dict[tuple[int, int], str],
    cells: frozenset[tuple[int, int]],
    name: str,
    label: str,
) -> None:
    for xy in cells:
        previous = owners.get(xy)
        if previous is not None:
            raise JsonDataError(f"{label}坐标域重叠：{xy} -> {previous}、{name}")
        owners[xy] = name


def _require_full_coverage(
    owners: Mapping[tuple[int, int], object],
    bounds: tuple[int, int, int, int],
    label: str,
) -> None:
    expected = {
        (x, y)
        for y in range(bounds[2], bounds[3] + 1)
        for x in range(bounds[0], bounds[1] + 1)
    }
    actual = set(owners)
    if actual != expected:
        missing = len(expected - actual)
        extra = len(actual - expected)
        raise JsonDataError(f"{label}必须完整覆盖世界坐标：缺少{missing}，越界{extra}")


def _connected(cells: frozenset[tuple[int, int]]) -> bool:
    if not cells:
        return False
    reached: set[tuple[int, int]] = set()
    queue = deque([next(iter(cells))])
    while queue:
        xy = queue.popleft()
        if xy in reached:
            continue
        reached.add(xy)
        x, y = xy
        queue.extend(
            neighbor
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
            if neighbor in cells and neighbor not in reached
        )
    return reached == cells


def _cell_bounds(cells: frozenset[tuple[int, int]]) -> tuple[int, int, int, int]:
    if not cells:
        raise JsonDataError("坐标域不能为空")
    xs = [xy[0] for xy in cells]
    ys = [xy[1] for xy in cells]
    return (min(xs), max(xs), min(ys), max(ys))


def _label_cell(cells: frozenset[tuple[int, int]]) -> tuple[int, int]:
    center_x = sum(x for x, _ in cells) / len(cells)
    center_y = sum(y for _, y in cells) / len(cells)
    return min(
        cells,
        key=lambda xy: (
            (xy[0] - center_x) ** 2 + (xy[1] - center_y) ** 2,
            xy[1],
            xy[0],
        ),
    )


def _map_coordinate_bands(
    cells: frozenset[tuple[int, int]],
) -> tuple[MapCoordinateBand, ...]:
    by_y: dict[int, list[int]] = {}
    for x, y in cells:
        by_y.setdefault(y, []).append(x)
    bands = []
    for y, xs in sorted(by_y.items()):
        ranges: list[tuple[int, int]] = []
        start = previous = min(xs)
        for x in sorted(xs)[1:]:
            if x == previous + 1:
                previous = x
                continue
            ranges.append((start, previous))
            start = previous = x
        ranges.append((start, previous))
        bands.append(MapCoordinateBand(y=y, x_ranges=tuple(ranges)))
    return tuple(bands)


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item) for item in value)


def _validate_location_data(
    raw: Mapping[str, object],
    location_name: str,
    feature_requirements: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]],
    feature_config_functions: Sequence[str] = (),
) -> None:
    """地点身份和层级来自路径；主体 JSON 只保存地点业务数据。"""

    unknown = tuple(sorted(set(raw) - _LOCATION_FIELDS))
    if unknown:
        raise JsonDataError(
            f"地点 {location_name} 存在未声明字段：{'、'.join(unknown)}；"
            "身份和层级必须由目录表达"
        )
    coordinates = raw.get("坐标")
    if not _valid_pair(coordinates):
        raise JsonDataError(f"地点 {location_name}.坐标必须是两个整数")
    description = raw.get("说明")
    if not isinstance(description, str) or not description.strip():
        raise JsonDataError(f"地点 {location_name}.说明必须是非空字符串")
    functions = _required_strings(raw.get("可用功能"), f"地点 {location_name}.可用功能")
    unknown_functions = tuple(sorted(set(functions) - set(feature_requirements)))
    if unknown_functions:
        raise JsonDataError(
            f"地点 {location_name} 使用未登记功能：{'、'.join(unknown_functions)}"
        )
    required_fields: set[str] = set()
    positive_range_fields: set[str] = set()
    for function in functions:
        nonempty, positive_range = feature_requirements[function]
        required_fields.update(nonempty)
        required_fields.update(positive_range)
        positive_range_fields.update(positive_range)
    configs = raw.get("功能配置", {})
    if not isinstance(configs, Mapping):
        raise JsonDataError(f"地点 {location_name}.功能配置必须是对象")
    unknown_configs = set(configs) - set(functions)
    if unknown_configs:
        raise JsonDataError(
            f"地点 {location_name}.功能配置包含未声明功能："
            f"{'、'.join(sorted(unknown_configs))}"
        )
    for function, config in configs.items():
        if not isinstance(config, Mapping):
            raise JsonDataError(
                f"地点 {location_name}.功能配置.{function} 必须是对象"
            )
    missing_configs = (set(functions) & set(feature_config_functions)) - set(configs)
    if missing_configs:
        raise JsonDataError(
            f"地点 {location_name} 缺少专属功能配置：{'、'.join(sorted(missing_configs))}"
        )
    declared_optional = set(raw) - {"坐标", "说明", "可用功能", "功能配置"}
    undeclared_optional = declared_optional - required_fields
    if undeclared_optional:
        raise JsonDataError(
            f"地点 {location_name} 字段没有对应功能要求："
            f"{'、'.join(sorted(undeclared_optional))}"
        )
    for field in sorted(required_fields):
        value = raw.get(field)
        if field in positive_range_fields:
            _positive_range(value, f"地点 {location_name}.{field}")
        elif not _nonempty(value):
            raise JsonDataError(f"地点 {location_name}.{field} 必须非空")


def _numbers(value: object) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(int(item) for item in value)


def _environment_ids(data: JsonDataService) -> dict[str, str]:
    result: dict[str, str] = {}
    for environment_id, raw in data.entities("战场环境").items():
        name = str(raw.get("名称") or "").strip()
        if not name or name in result:
            raise JsonDataError("战场环境名称不能为空或重复")
        result[name] = environment_id
    return result


def _feature_definitions(
    value: object,
) -> tuple[
    dict[str, tuple[str, ...]],
    dict[str, tuple[tuple[str, ...], tuple[str, ...]]],
    frozenset[str],
]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError("地点功能定义必须是字典列表")
    contents: dict[str, tuple[str, ...]] = {}
    requirements: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    config_functions: set[str] = set()
    for raw in value:
        if not isinstance(raw, Mapping):
            raise JsonDataError("地点功能定义只能包含对象")
        unknown = set(raw) - {"名称", "同目录内容", "要求", "地点配置"}
        if unknown:
            raise JsonDataError(
                f"地点功能定义存在未知字段：{'、'.join(sorted(unknown))}"
            )
        name_value = raw.get("名称")
        name = name_value.strip() if isinstance(name_value, str) else ""
        if not name or name in contents:
            raise JsonDataError("地点功能名称不能为空或重复")
        location_config = raw.get("地点配置", False)
        if not isinstance(location_config, bool):
            raise JsonDataError(f"地点功能 {name}.地点配置必须是布尔值")
        if location_config:
            config_functions.add(name)
        sections = _required_strings(
            raw.get("同目录内容"),
            f"地点功能 {name}.同目录内容",
            allow_empty=True,
        )
        if any(
            section not in {
                "道侣", "敌人", "商店", "炼器工匠", "炼丹师", "阵师",
                "讨伐", "讨伐首领", "讨伐辅助", "讨伐属从",
            }
            for section in sections
        ):
            raise JsonDataError(f"地点功能使用未知同目录内容：{name} -> {sections}")
        requirement = raw.get("要求")
        if not isinstance(requirement, Mapping):
            raise JsonDataError(f"地点功能 {name}.要求必须是对象")
        unknown = set(requirement) - {"非空字段", "正数范围字段"}
        if unknown:
            raise JsonDataError(
                f"地点功能 {name}.要求存在未知字段：{'、'.join(sorted(unknown))}"
            )
        nonempty = _required_strings(
            requirement.get("非空字段"),
            f"地点功能 {name}.要求.非空字段",
            allow_empty=True,
        )
        positive_range = _required_strings(
            requirement.get("正数范围字段"),
            f"地点功能 {name}.要求.正数范围字段",
            allow_empty=True,
        )
        overlap = set(nonempty) & set(positive_range)
        if overlap:
            raise JsonDataError(
                f"地点功能 {name} 的要求字段重复：{'、'.join(sorted(overlap))}"
            )
        unknown_fields = (set(nonempty) | set(positive_range)) - _LOCATION_FIELDS
        if unknown_fields:
            raise JsonDataError(
                f"地点功能 {name} 要求了地点未声明字段："
                f"{'、'.join(sorted(unknown_fields))}"
            )
        contents[name] = sections
        requirements[name] = (nonempty, positive_range)
    return contents, requirements, frozenset(config_functions)


def _required_strings(
    value: object,
    label: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError(f"{label}必须是字符串数组")
    if any(not isinstance(item, str) for item in value):
        raise JsonDataError(f"{label}只能包含字符串")
    result = tuple(item.strip() for item in value)
    if (not allow_empty and not result) or any(not item for item in result):
        raise JsonDataError(f"{label}不能为空或包含空字符串")
    if len(result) != len(set(result)):
        raise JsonDataError(f"{label}不能重复")
    return result


def _nonempty(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return bool(value)
    return True


def _positive_range(value: object, label: str) -> tuple[int, int]:
    if not _valid_pair(value) or value[0] < 1 or value[1] < value[0]:
        raise JsonDataError(f"{label}必须是两个顺序正整数")
    return (value[0], value[1])


__all__ = ["WorldService"]
