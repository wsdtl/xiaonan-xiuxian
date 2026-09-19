"""世界核心内部的 JSON 驱动行程规划器。"""

from __future__ import annotations

import heapq
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise

from game.core.data import (
    JsonDataError,
    JsonDataService,
    mapping as _mapping,
    positive_int as _positive_int,
)

from .contracts import (
    JourneyMetrics,
    JourneyPassageSegment,
    JourneyPlan,
    LocationView,
    MapRoad,
)

XY = tuple[int, int]
RouteState = tuple[XY, str]
RouteCost = tuple[float, int, float]

_METRIC_DEFINITIONS = (
    ("水平距离", "米"),
    ("道路段数", "段"),
    ("地形段数", "段"),
    ("最低海拔", "米"),
    ("最高海拔", "米"),
    ("累计爬升", "米"),
    ("累计下降", "米"),
    ("最大单步升高", "米"),
    ("最大单步降低", "米"),
    ("最大上坡千分比", "千分比"),
    ("最大下坡千分比", "千分比"),
    ("折算路程", "米"),
)


@dataclass(frozen=True)
class _RealmNarrative:
    realm_id: str
    method: str
    departure: str
    en_route: str
    arrival: str


class JourneyPlanner:
    """只解释行路规则和地图事实，不持有玩家状态。"""

    def __init__(
        self,
        data: JsonDataService,
        *,
        bounds: tuple[int, int, int, int],
        cell_size_meters: int,
        surface: tuple[tuple[int, ...], ...],
        region_by_xy: Mapping[XY, str],
        terrain_by_xy: Mapping[XY, tuple[str, str]],
        location_name_by_xy: Mapping[XY, str],
        roads: tuple[MapRoad, ...],
    ) -> None:
        self._bounds = bounds
        self._cell_size = cell_size_meters
        self._surface = surface
        self._region_by_xy = region_by_xy
        self._terrain_by_xy = terrain_by_xy
        self._location_name_by_xy = location_name_by_xy
        self._road_edges = _road_edges(roads)

        rules = _mapping(_single(data, "行路规则", "行程"), "行路规则.行程")
        display = _mapping(_single(data, "行路展示", "行程"), "行路展示.行程")
        self._moves, self._diagonal_multiplier = _coordinate_rules(rules)
        self._allow_off_road, self._road_overrides_terrain = _network_rules(rules)
        self._horizontal_weight, self._ascent_weight, self._descent_weight = (
            _distance_rules(rules)
        )
        self._validate_route_sort(rules)
        self._road_multipliers = _multipliers(
            _single(data, "道路通行规则", "道路通行"), "道路", "道路通行规则"
        )
        self._terrain_multipliers = _multipliers(
            _single(data, "地形通行规则", "地形通行"), "地形", "地形通行规则"
        )
        self._validate_multiplier_coverage(roads)

        self._direction_words = _direction_words(display, self._moves)
        self._road_words = _road_words(display, self._road_multipliers)
        self._terrain_words = _mapping(display.get("地形措辞"), "行路展示.地形措辞")
        self._ascent_words = _threshold_words(
            display.get("爬升措辞"), "累计爬升上限", "行路展示.爬升措辞"
        )
        self._altitude_words = _threshold_words(
            display.get("海拔措辞"), "最高海拔上限", "行路展示.海拔措辞"
        )
        self._realms, self._realm_names = _realm_narratives(data, display)
        self._narrative = _mapping(display.get("叙事"), "行路展示.叙事")
        self._narrative_order = tuple(
            str(value or "").strip()
            for value in _sequence(self._narrative.get("顺序"), "行路展示.叙事.顺序")
        )
        expected_narrative_order = {
            "起程",
            "通行",
            "经由",
            "途中",
            "地势",
            "抵达",
            "总览",
        }
        if (
            len(self._narrative_order) != len(expected_narrative_order)
            or set(self._narrative_order) != expected_narrative_order
        ):
            raise JsonDataError("行路展示.叙事.顺序必须完整且唯一地定义七段叙事")
        limits = _mapping(display.get("展示限制"), "行路展示.展示限制")
        self._passage_limit = _positive_int(limits.get("最多通行段"), "最多通行段")
        self._via_limit = _positive_int(limits.get("最多经由地点"), "最多经由地点")
        distance = _mapping(display.get("距离"), "行路展示.距离")
        self._meters_per_li = _positive_int(distance.get("每里米数"), "每里米数")
        self._li_rounding = _positive_int(distance.get("约数步长"), "约数步长")
        _validate_metric_definitions(data)
        _required_texts(
            self._narrative,
            "行路展示.叙事",
            (
                "通行分隔",
                "通行省略",
                "经由",
                "经由省略后缀",
                "地势",
                "总览高地",
                "总览低地",
            ),
        )

    @property
    def realm_count(self) -> int:
        return len(self._realms)

    def plan(
        self,
        *,
        origin: LocationView,
        destination: LocationView,
        realm_id: str,
    ) -> JourneyPlan:
        if origin.xy == destination.xy:
            raise ValueError("起点与终点不能是同一坐标")
        realm = self._realms.get(str(realm_id or "").strip())
        if realm is None:
            raise JsonDataError(f"境界没有行路叙事：{realm_id or '<空>'}")
        route = self._find_route(origin.xy, destination.xy)
        passages = self._passages(route)
        metrics = self._metrics(route, passages)
        via_locations = tuple(
            name
            for xy in route[1:-1]
            if (name := self._location_name_by_xy.get(xy)) is not None
        )
        via_locations = tuple(dict.fromkeys(via_locations))
        narrative = self._render_narrative(
            origin,
            destination,
            realm,
            route,
            passages,
            via_locations,
            metrics,
        )
        return JourneyPlan(
            origin=origin,
            destination=destination,
            realm_id=realm.realm_id,
            realm_name=self._realm_names[realm.realm_id],
            travel_method=realm.method,
            route=route,
            passages=passages,
            via_locations=via_locations,
            metrics=metrics,
            narrative=narrative,
        )

    def _find_route(self, start: XY, goal: XY) -> tuple[XY, ...]:
        start_state: RouteState = (start, "")
        best: dict[RouteState, RouteCost] = {start_state: (0.0, 0, 0.0)}
        previous: dict[RouteState, RouteState] = {}
        queue: list[tuple[float, int, float, int, int, str]] = [
            (0.0, 0, 0.0, start[0], start[1], "")
        ]
        goal_state: RouteState | None = None
        while queue:
            weighted, road_segments, horizontal, x, y, last_road = heapq.heappop(queue)
            state = ((x, y), last_road)
            cost = (weighted, road_segments, horizontal)
            if best.get(state) != cost:
                continue
            if state[0] == goal:
                goal_state = state
                break
            for neighbor in self._neighbors(state[0]):
                road_type = self._road_edges.get(_edge(state[0], neighbor), "")
                if not road_type and not self._allow_off_road:
                    continue
                step_horizontal = self._step_horizontal(state[0], neighbor)
                multiplier = self._movement_multiplier(state[0], neighbor, road_type)
                altitude_delta = self._altitude(neighbor) - self._altitude(state[0])
                step_weighted = step_horizontal * multiplier * self._horizontal_weight
                if altitude_delta > 0:
                    step_weighted += altitude_delta * self._ascent_weight
                else:
                    step_weighted += -altitude_delta * self._descent_weight
                next_last_road = road_type
                segment_increment = int(bool(road_type) and road_type != last_road)
                next_cost = (
                    weighted + step_weighted,
                    road_segments + segment_increment,
                    horizontal + step_horizontal,
                )
                next_state = (neighbor, next_last_road)
                if next_cost >= best.get(next_state, (math.inf, math.inf, math.inf)):
                    continue
                best[next_state] = next_cost
                previous[next_state] = state
                heapq.heappush(
                    queue,
                    (*next_cost, neighbor[0], neighbor[1], next_last_road),
                )
        if goal_state is None:
            raise JsonDataError(f"地图规则下不存在可达行程：{start} -> {goal}")
        route: list[XY] = [goal_state[0]]
        state = goal_state
        while state != start_state:
            state = previous[state]
            route.append(state[0])
        route.reverse()
        return tuple(route)

    def _neighbors(self, xy: XY) -> tuple[XY, ...]:
        x, y = xy
        x_min, x_max, y_min, y_max = self._bounds
        return tuple(
            (x + dx, y + dy)
            for dx, dy in self._moves
            if x_min <= x + dx <= x_max and y_min <= y + dy <= y_max
        )

    def _step_horizontal(self, start: XY, end: XY) -> float:
        diagonal = start[0] != end[0] and start[1] != end[1]
        return self._cell_size * (self._diagonal_multiplier if diagonal else 1.0)

    def _movement_multiplier(self, start: XY, end: XY, road_type: str) -> float:
        if road_type and self._road_overrides_terrain:
            return self._road_multipliers[road_type]
        start_terrain = self._terrain_by_xy[start][1]
        end_terrain = self._terrain_by_xy[end][1]
        terrain = (
            self._terrain_multipliers[start_terrain]
            + self._terrain_multipliers[end_terrain]
        ) / 2
        if road_type:
            return terrain * self._road_multipliers[road_type]
        return terrain

    def _passages(self, route: tuple[XY, ...]) -> tuple[JourneyPassageSegment, ...]:
        groups: list[tuple[str, str, XY, XY, float]] = []
        for start, end in pairwise(route):
            road_type = self._road_edges.get(_edge(start, end), "")
            kind = "道路" if road_type else "地形"
            name = road_type or self._terrain_by_xy[end][1]
            distance = self._step_horizontal(start, end)
            if groups and groups[-1][:2] == (kind, name):
                previous = groups[-1]
                groups[-1] = (*previous[:3], end, previous[4] + distance)
            else:
                groups.append((kind, name, start, end, distance))
        return tuple(
            JourneyPassageSegment(
                kind=kind,
                name=name,
                start_xy=start,
                end_xy=end,
                direction=_direction(start, end),
                horizontal_distance_m=_round(distance),
            )
            for kind, name, start, end, distance in groups
        )

    def _metrics(
        self,
        route: tuple[XY, ...],
        passages: tuple[JourneyPassageSegment, ...],
    ) -> JourneyMetrics:
        altitudes = tuple(self._altitude(xy) for xy in route)
        horizontal = 0.0
        weighted = 0.0
        ascents: list[int] = []
        descents: list[int] = []
        uphill: list[int] = []
        downhill: list[int] = []
        for start, end in pairwise(route):
            step_horizontal = self._step_horizontal(start, end)
            road_type = self._road_edges.get(_edge(start, end), "")
            delta = self._altitude(end) - self._altitude(start)
            ascent = max(0, delta)
            descent = max(0, -delta)
            horizontal += step_horizontal
            weighted += (
                step_horizontal
                * self._movement_multiplier(start, end, road_type)
                * self._horizontal_weight
                + ascent * self._ascent_weight
                + descent * self._descent_weight
            )
            ascents.append(ascent)
            descents.append(descent)
            uphill.append(_round(ascent * 1000 / step_horizontal))
            downhill.append(_round(descent * 1000 / step_horizontal))
        return JourneyMetrics(
            horizontal_distance_m=_round(horizontal),
            road_segment_count=sum(item.kind == "道路" for item in passages),
            terrain_segment_count=sum(item.kind == "地形" for item in passages),
            minimum_altitude_m=min(altitudes),
            maximum_altitude_m=max(altitudes),
            total_ascent_m=sum(ascents),
            total_descent_m=sum(descents),
            maximum_step_ascent_m=max(ascents, default=0),
            maximum_step_descent_m=max(descents, default=0),
            maximum_uphill_permille=max(uphill, default=0),
            maximum_downhill_permille=max(downhill, default=0),
            weighted_distance_m=_round(weighted),
        )

    def _render_narrative(
        self,
        origin: LocationView,
        destination: LocationView,
        realm: _RealmNarrative,
        route: tuple[XY, ...],
        passages: tuple[JourneyPassageSegment, ...],
        via_locations: tuple[str, ...],
        metrics: JourneyMetrics,
    ) -> tuple[str, ...]:
        start_name = _location_label(origin)
        end_name = _location_label(destination)
        values = {"起点": start_name, "终点": end_name}
        sections = {"起程": realm.departure.format_map(values)}
        passage_phrases = tuple(
            self._passage_phrase(segment, index == 0)
            for index, segment in enumerate(passages[: self._passage_limit])
        )
        if len(passages) > self._passage_limit:
            passage_phrases += (str(self._narrative["通行省略"]),)
        if passage_phrases:
            sections["通行"] = (
                str(self._narrative["通行分隔"]).join(passage_phrases) + "。"
            )
        else:
            sections["通行"] = ""
        if via_locations:
            displayed = via_locations[: self._via_limit]
            joined = "、".join(displayed)
            if len(via_locations) > self._via_limit:
                joined += str(self._narrative["经由省略后缀"])
            sections["经由"] = str(self._narrative["经由"]).format_map({"地点": joined})
        else:
            sections["经由"] = str(self._narrative.get("没有经由地点") or "")
        sections["途中"] = realm.en_route
        terrain_candidates = route[1:-1] or route
        highest_xy = max(terrain_candidates, key=lambda xy: self._altitude(xy))
        terrain_turn = self._position_label(highest_xy)
        ascent_word = _threshold_text(self._ascent_words, metrics.total_ascent_m)
        sections["地势"] = str(self._narrative["地势"]).format_map(
            {"地势转折": terrain_turn, "爬升措辞": ascent_word},
        )
        sections["抵达"] = realm.arrival.format_map(values)
        altitude_word = _threshold_text(
            self._altitude_words, metrics.maximum_altitude_m
        )
        li = metrics.horizontal_distance_m / self._meters_per_li
        rounded_li = _round_to_step(li, self._li_rounding)
        template = "总览高地" if metrics.maximum_altitude_m > 0 else "总览低地"
        sections["总览"] = str(self._narrative[template]).format_map(
            {"里程": rounded_li, "最高海拔": metrics.maximum_altitude_m, "海拔措辞": altitude_word},
        )
        return tuple(
            sections[section] for section in self._narrative_order if sections[section]
        )

    def _passage_phrase(self, segment: JourneyPassageSegment, first: bool) -> str:
        direction = self._direction_words[segment.direction]
        if segment.kind == "道路":
            words = self._road_words[segment.name]
            template = words["起行"] if first else words["转入"]
        else:
            template = str(self._terrain_words["起行" if first else "转入"])
        return str(template).format_map({"方向": direction, "地形": segment.name})

    def _position_label(self, xy: XY) -> str:
        location_name = self._location_name_by_xy.get(xy)
        if location_name:
            return location_name
        zone_name, terrain = self._terrain_by_xy[xy]
        if zone_name:
            return zone_name
        return f"{self._region_by_xy[xy]}·{terrain}（{xy[0]}, {xy[1]}）"

    def _altitude(self, xy: XY) -> int:
        return self._surface[xy[1] - self._bounds[2]][xy[0] - self._bounds[0]]

    def _validate_route_sort(self, rules: Mapping[str, object]) -> None:
        automatic = _mapping(rules.get("自动选路"), "行路规则.自动选路")
        rows = _sequence(automatic.get("排序"), "行路规则.自动选路.排序")
        actual = tuple(
            (
                str(_mapping(row, "自动选路.排序").get("指标") or "").strip(),
                str(_mapping(row, "自动选路.排序").get("顺序") or "").strip(),
            )
            for row in rows
        )
        expected = (("折算路程", "升序"), ("道路段数", "升序"), ("水平距离", "升序"))
        if actual != expected:
            raise JsonDataError(f"自动选路排序必须是：{expected}")

    def _validate_multiplier_coverage(self, roads: tuple[MapRoad, ...]) -> None:
        road_types = {road.road_type for road in roads}
        if set(self._road_multipliers) != road_types:
            raise JsonDataError("道路通行倍率必须完整覆盖世界道路类型")
        terrain_types = {terrain for _, terrain in self._terrain_by_xy.values()}
        if set(self._terrain_multipliers) != terrain_types:
            raise JsonDataError("地形通行倍率必须完整覆盖世界地形")


def _single(data: JsonDataService, dataset: str, file_id: str) -> object:
    value = data.dataset(dataset).get(file_id)
    if value is None:
        raise JsonDataError(f"{dataset}缺少{file_id}.json")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError(f"{label}必须是列表")
    return value


def _positive_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise JsonDataError(f"{label}必须是正数")
    return float(value)


def _coordinate_rules(rules: Mapping[str, object]) -> tuple[tuple[XY, ...], float]:
    values = _mapping(rules.get("坐标规则"), "行路规则.坐标规则")
    moves = tuple(
        (int(row[0]), int(row[1]))
        for row in _sequence(values.get("允许相邻步"), "允许相邻步")
        if isinstance(row, Sequence)
        and not isinstance(row, (str, bytes))
        and len(row) == 2
        and all(isinstance(item, int) and not isinstance(item, bool) for item in row)
    )
    expected = {(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - {(0, 0)}
    if len(moves) != 8 or set(moves) != expected:
        raise JsonDataError("允许相邻步必须完整且唯一地定义八方向")
    return moves, _positive_number(values.get("斜向距离倍率"), "斜向距离倍率")


def _network_rules(rules: Mapping[str, object]) -> tuple[bool, bool]:
    values = _mapping(rules.get("路网规则"), "行路规则.路网规则")
    if values.get("默认双向") is not True or values.get("道路边类型唯一") is not True:
        raise JsonDataError("当前行路核心要求道路默认双向且道路边类型唯一")
    allow_off_road = values.get("允许非道路通行")
    road_overrides = values.get("道路覆盖地形")
    if not isinstance(allow_off_road, bool) or not isinstance(road_overrides, bool):
        raise JsonDataError("路网规则布尔字段无效")
    if values.get("非道路地形倍率") != "两端平均":
        raise JsonDataError("当前行路核心只接受非道路地形倍率两端平均")
    return allow_off_road, road_overrides


def _distance_rules(rules: Mapping[str, object]) -> tuple[float, float, float]:
    values = _mapping(rules.get("路程折算"), "行路规则.路程折算")
    if values.get("取整") != "四舍五入":
        raise JsonDataError("当前行路核心只接受折算路程四舍五入")
    return (
        _positive_number(values.get("水平每米"), "水平每米"),
        _positive_number(values.get("上升每米"), "上升每米"),
        _positive_number(values.get("下降每米"), "下降每米"),
    )


def _multipliers(value: object, key: str, label: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for index, raw in enumerate(_sequence(value, label)):
        row = _mapping(raw, f"{label}[{index}]")
        name = str(row.get(key) or "").strip()
        if not name or name in result:
            raise JsonDataError(f"{label}的{key}不能为空或重复")
        result[name] = _positive_number(row.get("倍率"), f"{label}.{name}.倍率")
    return result


def _direction_words(
    display: Mapping[str, object], moves: tuple[XY, ...]
) -> dict[XY, str]:
    result: dict[XY, str] = {}
    for raw in _sequence(display.get("方向措辞"), "行路展示.方向措辞"):
        row = _mapping(raw, "方向措辞")
        direction = row.get("方向")
        if (
            not isinstance(direction, Sequence)
            or isinstance(direction, (str, bytes))
            or len(direction) != 2
            or any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in direction
            )
        ):
            raise JsonDataError("方向措辞.方向必须是坐标差")
        key = (direction[0], direction[1])
        word = str(row.get("措辞") or "").strip()
        if not word or key in result:
            raise JsonDataError("方向措辞不能为空或重复")
        result[key] = word
    if set(result) != set(moves):
        raise JsonDataError("方向措辞必须完整覆盖允许相邻步")
    return result


def _road_words(
    display: Mapping[str, object], multipliers: Mapping[str, float]
) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for raw in _sequence(display.get("道路措辞"), "行路展示.道路措辞"):
        row = _mapping(raw, "道路措辞")
        road = str(row.get("道路") or "").strip()
        _required_texts(row, f"道路措辞.{road}", ("起行", "转入"))
        if not road or road in result:
            raise JsonDataError("道路措辞的道路不能为空或重复")
        result[road] = row
    if set(result) != set(multipliers):
        raise JsonDataError("道路措辞必须完整覆盖道路通行规则")
    return result


def _threshold_words(
    value: object, threshold_key: str, label: str
) -> tuple[tuple[int | None, str], ...]:
    result: list[tuple[int | None, str]] = []
    for raw in _sequence(value, label):
        row = _mapping(raw, label)
        threshold = row.get(threshold_key)
        if threshold is not None and (
            isinstance(threshold, bool) or not isinstance(threshold, int)
        ):
            raise JsonDataError(f"{label}.{threshold_key}必须是整数或null")
        text = str(row.get("措辞") or "").strip()
        if not text:
            raise JsonDataError(f"{label}.措辞不能为空")
        result.append((threshold, text))
    if not result or result[-1][0] is not None:
        raise JsonDataError(f"{label}最后一档必须用null兜底")
    finite = [threshold for threshold, _ in result if threshold is not None]
    if finite != sorted(finite) or len(finite) != len(set(finite)):
        raise JsonDataError(f"{label}阈值必须严格升序")
    return tuple(result)


def _realm_narratives(
    data: JsonDataService, display: Mapping[str, object]
) -> tuple[dict[str, _RealmNarrative], dict[str, str]]:
    realms = data.entities("境界")
    result: dict[str, _RealmNarrative] = {}
    names: dict[str, str] = {}
    for raw in _sequence(display.get("境界行路"), "行路展示.境界行路"):
        row = _mapping(raw, "境界行路")
        realm_id = str(row.get("境界") or "").strip()
        _required_texts(row, f"境界行路.{realm_id}", ("方式", "起程", "途中", "抵达"))
        if realm_id in result:
            raise JsonDataError(f"境界行路重复：{realm_id}")
        narrative = _RealmNarrative(
            realm_id,
            str(row["方式"]),
            str(row["起程"]),
            str(row["途中"]),
            str(row["抵达"]),
        )
        result[realm_id] = narrative
        names[realm_id] = str(realms.get(realm_id, {}).get("名称") or "").strip()
    if set(result) != set(realms):
        raise JsonDataError("境界行路必须与全部境界编号一一对应")
    identities = {
        (item.method, item.departure, item.en_route, item.arrival)
        for item in result.values()
    }
    if len(identities) != len(result):
        raise JsonDataError("每个境界必须拥有独立的行路方式和三段叙事")
    if any(not name for name in names.values()):
        raise JsonDataError("境界行路引用的境界必须具有名称")
    return result, names


def _validate_metric_definitions(data: JsonDataService) -> None:
    rows = _single(data, "行路定义", "行程指标")
    actual = tuple(
        (
            str(row.get("名称") or "").strip(),
            str(row.get("单位") or "").strip(),
        )
        for raw in _sequence(rows, "行程指标")
        for row in (_mapping(raw, "行程指标"),)
    )
    if actual != _METRIC_DEFINITIONS:
        raise JsonDataError("行程指标的名称、单位和顺序必须与公开契约一致")


def _required_texts(
    values: Mapping[str, object], label: str, fields: tuple[str, ...]
) -> None:
    missing = tuple(
        field
        for field in fields
        if not isinstance(values.get(field), str) or not str(values[field]).strip()
    )
    if missing:
        raise JsonDataError(f"{label}缺少非空文本：{'、'.join(missing)}")


def _road_edges(roads: tuple[MapRoad, ...]) -> dict[tuple[XY, XY], str]:
    result: dict[tuple[XY, XY], str] = {}
    for road in roads:
        for start, end in pairwise(road.coordinates):
            key = _edge(start, end)
            previous = result.get(key)
            if previous is not None and previous != road.road_type:
                raise JsonDataError(
                    f"同一坐标边存在不同道路类型：{key} -> {previous}、{road.road_type}"
                )
            result[key] = road.road_type
    return result


def _edge(start: XY, end: XY) -> tuple[XY, XY]:
    return (start, end) if start < end else (end, start)


def _direction(start: XY, end: XY) -> XY:
    return (_sign(end[0] - start[0]), _sign(end[1] - start[1]))


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


def _round(value: float) -> int:
    return math.floor(value + 0.5)


def _round_to_step(value: float, step: int) -> int:
    return max(step, _round(value / step) * step)


def _threshold_text(rows: tuple[tuple[int | None, str], ...], value: int) -> str:
    return next(
        text for threshold, text in rows if threshold is None or value <= threshold
    )


def _location_label(location: LocationView) -> str:
    if location.location_name:
        return location.location_name
    return f"{location.region}·{location.terrain}（{location.xy[0]}, {location.xy[1]}）"


__all__ = ["JourneyPlanner"]
