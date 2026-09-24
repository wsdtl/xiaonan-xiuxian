"""由位置 JSON 规则驱动的玩家地表位置服务。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from game.core.data import (
    JsonDataError,
    JsonDataService,
    mapping as _mapping,
    positive_int as _positive_int,
)
from game.core.database import (
    DatabaseService,
    LocationMutation,
    StateConflictError,
    TransactionCommand,
)
from game.core.world import LocationQuery, WorldService

from .contracts import (
    GroupLocationMoveCommand,
    GroupLocationMoveResult,
    LocationConflictError,
    LocationMissingError,
    LocationMoveCommand,
    LocationMoveResult,
    LocationServiceStatus,
    NearbyPlayerCandidates,
    NearbyPlayerLocation,
    PlayerLocation,
    SpaceChangeCommand,
    SpaceChangeResult,
)


class LocationService:
    """拥有玩家地表位置写权限和空间范围查询权的唯一核心服务。"""

    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService,
        world: WorldService,
    ) -> None:
        self._data = data
        self._database = database
        self._world = world
        self._initialized = False
        self._radius_meters = 0
        self._page_size = 0
        self._visible_limit = 0
        self._candidate_limit = 0
        self._cell_size_meters = 0

    def initialize(self) -> LocationServiceStatus:
        if self._initialized:
            raise RuntimeError("玩家位置核心微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据服务必须先于玩家位置服务启动")
        if not self._database.status().initialized:
            raise RuntimeError("核心数据库必须先于玩家位置服务启动")
        if not self._world.status().initialized:
            raise RuntimeError("世界核心必须先于玩家位置服务启动")
        rules = self._data.dataset("位置规则")
        nearby = rules.get("附近")
        if not isinstance(nearby, Mapping):
            raise JsonDataError("位置规则缺少附近.json")
        cultivators = _mapping(nearby.get("修士"), "附近.修士")
        self._radius_meters = _positive_int(
            cultivators.get("范围米数"), "附近.修士.范围米数"
        )
        self._page_size = _positive_int(
            cultivators.get("每页数量"), "附近.修士.每页数量"
        )
        self._visible_limit = _positive_int(
            cultivators.get("最多可见数量"), "附近.修士.最多可见数量"
        )
        self._candidate_limit = _positive_int(
            cultivators.get("最多候选数量"), "附近.修士.最多候选数量"
        )
        if self._page_size > self._visible_limit:
            raise JsonDataError("附近修士每页数量不能超过最多可见数量")
        if self._visible_limit > self._candidate_limit:
            raise JsonDataError("附近修士最多可见数量不能超过最多候选数量")
        self._cell_size_meters = self._world.map_view().cell_size_meters
        self._initialized = True
        return self.status()

    def status(self) -> LocationServiceStatus:
        location_count = (
            self._database.status().location_count if self._initialized else 0
        )
        return LocationServiceStatus(
            initialized=self._initialized,
            player_count=location_count,
            nearby_radius_meters=self._radius_meters,
            nearby_page_size=self._page_size,
            nearby_visible_limit=self._visible_limit,
        )

    def initial_mutation(self, user_id: str, xy: tuple[int, int]) -> LocationMutation:
        self._require_initialized()
        normalized_user_id = _text(user_id, "user_id")
        validated = self._world.locate(LocationQuery(xy=_xy(xy))).xy
        return LocationMutation(normalized_user_id, validated, 0)

    async def current(self, user_id: str) -> PlayerLocation:
        self._require_initialized()
        normalized_user_id = _text(user_id, "user_id")
        record = await self._database.get_location(normalized_user_id)
        if record is None:
            raise LocationMissingError("人物缺少地表位置")
        return PlayerLocation(
            record.user_id,
            record.xy,
            record.version,
            record.updated_at,
            record.space_type,
            record.space_id,
        )

    async def current_many(
        self, user_ids: tuple[str, ...]
    ) -> tuple[PlayerLocation, ...]:
        """批量读一批人物的当前位置，语义与逐个 `current` 等价。

        一条连接读完；**任一人没有位置就抛同一句话的 `LocationMissingError`**
        （逐个读时也是在缺位置的那个人身上抛），返回值顺序与输入一致。
        """

        self._require_initialized()
        normalized = tuple(_text(value, "user_id") for value in user_ids)
        records = {
            record.user_id: record
            for record in await self._database.get_locations(normalized)
        }
        values: list[PlayerLocation] = []
        for user_id in normalized:
            record = records.get(user_id)
            if record is None:
                raise LocationMissingError("人物缺少地表位置")
            values.append(
                PlayerLocation(
                    record.user_id,
                    record.xy,
                    record.version,
                    record.updated_at,
                    record.space_type,
                    record.space_id,
                )
            )
        return tuple(values)

    async def nearby_players(self, user_id: str) -> NearbyPlayerCandidates:
        self._require_initialized()
        origin = await self.current(user_id)
        records = await self._database.nearby_locations(
            origin_xy=origin.xy,
            space_type=origin.space_type,
            space_id=origin.space_id,
            radius_meters=self._radius_meters,
            cell_size_meters=self._cell_size_meters,
            limit=self._candidate_limit + 1,
            exclude_user_id=origin.user_id,
        )
        limit_reached = len(records) > self._candidate_limit
        origin_altitude = self._world.locate(LocationQuery(xy=origin.xy)).altitude
        values: list[NearbyPlayerLocation] = []
        for value in records[: self._candidate_limit]:
            altitude = self._world.locate(LocationQuery(xy=value.xy)).altitude
            distance_squared = (
                value.horizontal_distance_squared_meters
                + (altitude - origin_altitude) ** 2
            )
            if distance_squared <= self._radius_meters**2:
                values.append(
                    NearbyPlayerLocation(
                        value.user_id,
                        value.xy,
                        distance_squared,
                        value.space_type,
                        value.space_id,
                    )
                )
        values.sort(
            key=lambda value: (
                value.distance_squared_meters,
                value.xy,
                value.user_id,
            )
        )
        return NearbyPlayerCandidates(
            origin=origin,
            values=tuple(values),
            candidate_limit_reached=limit_reached,
            page_size=self._page_size,
            visible_limit=self._visible_limit,
        )

    async def change_space(self, command: SpaceChangeCommand) -> SpaceChangeResult:
        self._require_initialized()
        owner = _text(command.owner_user_id, "owner_user_id")
        request_id = _text(command.request_id, "request_id")
        participants = tuple(
            _text(value, "participant_user_id")
            for value in command.participant_user_ids
        )
        if (
            not participants
            or participants[0] != owner
            or len(participants) != len(set(participants))
        ):
            raise ValueError("空间变更参与者顺序无效")
        space_type = _text(command.space_type, "space_type")
        space_id = str(command.space_id or "").strip()
        if space_type == "地表":
            if space_id:
                raise ValueError("地表空间不能包含空间编号")
        elif not space_id:
            raise ValueError("非地表空间必须包含空间编号")
        currents = await asyncio.gather(
            *(self.current(user_id) for user_id in participants)
        )
        if any(
            (current.space_type, current.space_id) == (space_type, space_id)
            for current in currents
        ):
            if all(
                (current.space_type, current.space_id) == (space_type, space_id)
                for current in currents
            ):
                return SpaceChangeResult(
                    owner, participants, space_type, space_id, False
                )
            raise LocationConflictError("同行空间状态不一致")
        if any(
            current.space_type != currents[0].space_type
            or current.space_id != currents[0].space_id
            for current in currents
        ):
            raise LocationConflictError("同行修士不在同一空间")
        try:
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id=owner,
                    request_id=request_id,
                    business_type="进入宗门洞天"
                    if space_type != "地表"
                    else "离开宗门洞天",
                    operations=tuple(
                        LocationMutation(
                            current.user_id,
                            current.xy,
                            current.version,
                            space_type,
                            space_id,
                        )
                        for current in currents
                    ),
                    payload={
                        "空间类型": space_type,
                        "空间编号": space_id,
                        "参与者": list(participants),
                    },
                )
            )
        except StateConflictError as exc:
            raise LocationConflictError("空间变更前位置已经改变") from exc
        return SpaceChangeResult(
            owner, participants, space_type, space_id, receipt.replayed
        )

    async def move(self, command: LocationMoveCommand) -> LocationMoveResult:
        self._require_initialized()
        user_id = _text(command.user_id, "user_id")
        request_id = _text(command.request_id, "request_id")
        expected = self._world.locate(
            LocationQuery(xy=_xy(command.expected_origin_xy))
        ).xy
        destination = self._world.locate(
            LocationQuery(xy=_xy(command.destination_xy))
        ).xy
        current = await self.current(user_id)
        if current.space_type != "地表":
            raise LocationConflictError("非地表空间不能执行世界行路")
        if current.xy == destination:
            return LocationMoveResult(user_id, current.xy, destination, False, False)
        if current.xy != expected:
            raise LocationConflictError(
                f"人物位置已经改变：预期 {expected}，当前 {current.xy}"
            )
        try:
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id=user_id,
                    request_id=request_id,
                    business_type="人物行路",
                    operations=(
                        LocationMutation(user_id, destination, current.version),
                    ),
                    payload={"起点": list(current.xy), "终点": list(destination)},
                )
            )
        except StateConflictError as exc:
            raise LocationConflictError("人物位置在行路结算前已经改变") from exc
        return LocationMoveResult(
            user_id,
            current.xy,
            destination,
            True,
            receipt.replayed,
        )

    async def move_many(
        self, command: GroupLocationMoveCommand
    ) -> GroupLocationMoveResult:
        """校验所有同行者仍在起点，并在一次事务中移动全部位置。"""

        self._require_initialized()
        owner = _text(command.owner_user_id, "owner_user_id")
        request_id = _text(command.request_id, "request_id")
        participants = tuple(
            _text(value, "participant_user_id")
            for value in command.participant_user_ids
        )
        if not participants or participants[0] != owner:
            raise ValueError("同行玩家顺序必须以发起者开头")
        if len(participants) != len(set(participants)):
            raise ValueError("同行玩家不能重复")
        expected = self._world.locate(
            LocationQuery(xy=_xy(command.expected_origin_xy))
        ).xy
        destination = self._world.locate(
            LocationQuery(xy=_xy(command.destination_xy))
        ).xy
        currents = await asyncio.gather(
            *(self.current(user_id) for user_id in participants)
        )
        if any(current.space_type != "地表" for current in currents):
            raise LocationConflictError("非地表空间不能执行世界行路")
        if any(current.xy != expected for current in currents):
            raise LocationConflictError("同行修士已经不在同一出发位置")
        if expected == destination:
            return GroupLocationMoveResult(
                owner, participants, expected, destination, False, False
            )
        try:
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id=owner,
                    request_id=request_id,
                    business_type="集体行路" if len(participants) > 1 else "人物行路",
                    operations=tuple(
                        LocationMutation(user_id, destination, current.version)
                        for user_id, current in zip(participants, currents, strict=True)
                    ),
                    payload={
                        "起点": list(expected),
                        "终点": list(destination),
                        "同行玩家": list(participants),
                    },
                )
            )
        except StateConflictError as exc:
            raise LocationConflictError("同行位置在行路结算前已经改变") from exc
        return GroupLocationMoveResult(
            owner,
            participants,
            expected,
            destination,
            True,
            receipt.replayed,
        )

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("玩家位置核心微服务尚未初始化")


def _text(value: object, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or normalized != value:
        raise ValueError(f"{label}必须是无首尾空白的非空字符串")
    return normalized


def _xy(value: object) -> tuple[int, int]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
    ):
        raise ValueError("xy必须是两个整数")
    return int(value[0]), int(value[1])


__all__ = ["LocationService"]
