"""预计算、按整轮解封并原子结算多人采集。"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from game.core.asset import AssetService, InventoryAdjustment
from game.core.character import CharacterService
from game.core.companion import CompanionService
from game.core.data import JsonDataError, JsonDataService
from game.core.database import (
    DatabaseService,
    StateAddress,
    StateConflictError,
    StateMutation,
    TransactionCommand,
)
from game.core.innate_treasure import (
    InnateTreasureActivation,
    InnateTreasureService,
)
from game.core.location import LocationService
from game.core.player_state import PlayerStateService, StateTransitionCommand
from game.core.pool import ALLOW_REPEATS, PoolRequest, PoolService
from game.core.sect import SectService
from game.core.sect_progress import SectProgressService
from game.core.world import LocationQuery, LocationView, WorldService

from .contracts import (
    GatheredItem,
    GatheringConflictError,
    GatheringLeaderRequiredError,
    GatheringModeStatus,
    GatheringProgress,
    GatheringSettlement,
    GatheringStartCommand,
    GatheringStarted,
    GatheringStateError,
    GatheringStatus,
    GatheringUserSummary,
)

SESSION_STATE = "gathering_session"
LATEST_STATE = "gathering_latest"
SETTLEMENT_STATE = "gathering_settlement"
KINDS = ("采药", "采矿")


@dataclass(frozen=True)
class _Mode:
    kind: str
    resource_category: str
    state_id: str
    seconds_per_round: int
    maximum_rounds: int
    maximum_seconds: int
    draws_per_unit: int
    quantity_per_draw: int
    maximum_participants: int

    def status(self) -> GatheringModeStatus:
        return GatheringModeStatus(
            self.kind,
            self.resource_category,
            self.state_id,
            self.seconds_per_round,
            self.maximum_rounds,
            self.maximum_seconds,
            self.draws_per_unit,
            self.quantity_per_draw,
        )


class GatheringService:
    """拥有采药与采矿会话、结果快照和最终结算的唯一核心边界。"""

    state_types = frozenset({SESSION_STATE, LATEST_STATE, SETTLEMENT_STATE})

    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService,
        world: WorldService,
        location: LocationService,
        character: CharacterService,
        companion: CompanionService,
        asset: AssetService,
        player_state: PlayerStateService,
        pool: PoolService,
        innate_treasure: InnateTreasureService,
        sect: SectService | None = None,
        progress: SectProgressService | None = None,
    ) -> None:
        self._data = data
        self._database = database
        self._world = world
        self._location = location
        self._character = character
        self._companion = companion
        self._asset = asset
        self._player_state = player_state
        self._pool = pool
        self._sect = sect
        self._progress = progress
        self._innate_treasure = innate_treasure
        self._initialized = False
        self._modes: dict[str, _Mode] = {}

    def initialize(self) -> GatheringStatus:
        if self._initialized:
            raise RuntimeError("采集核心已经初始化")
        if not self._innate_treasure.status().initialized:
            raise RuntimeError("先天灵宝核心必须先于采集核心启动")
        rules = self._data.dataset("玩法规则")
        modes = {kind: _parse_mode(kind, rules.get(kind)) for kind in KINDS}
        if len({mode.state_id for mode in modes.values()}) != len(modes):
            raise JsonDataError("采药与采矿必须使用不同的行为状态")
        if {mode.resource_category for mode in modes.values()} != {"灵植", "灵矿"}:
            raise JsonDataError("采药与采矿必须分别产出灵植和灵矿")
        self._modes = modes
        self._initialized = True
        return self.status()

    def status(self) -> GatheringStatus:
        return GatheringStatus(
            self._initialized,
            tuple(self._modes[kind].status() for kind in KINDS if kind in self._modes),
        )

    def mode_status(self, kind: str) -> GatheringModeStatus:
        return self._mode(kind).status()

    async def start(self, command: GatheringStartCommand) -> GatheringStarted:
        self._require_initialized()
        mode = self._mode(command.kind)
        owner = _user_id(command.owner_user_id)
        request_id = _text(command.request_id, "request_id")
        participants = _participants(
            owner, command.participant_user_ids, mode.maximum_participants
        )
        replay = await self._start_replay(mode, owner, request_id)
        if replay is not None:
            return replay
        seed = (
            command.seed
            if command.seed is not None
            else _stable_seed(mode.kind, owner, request_id)
        )
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("采集种子必须是整数")
        started_at = _utc(command.started_at)
        maximum_ends_at = started_at + timedelta(seconds=mode.maximum_seconds)
        session_id = hashlib.sha256(
            f"{mode.kind}\0{owner}\0{request_id}".encode()
        ).hexdigest()[:24]

        locations = [await self._location.current(user_id) for user_id in participants]
        if (
            len({(value.space_type, value.space_id, value.xy) for value in locations})
            != 1
        ):
            raise GatheringConflictError("同行修士必须位于同一空间和坐标")
        if locations[0].space_type != "地表":
            raise GatheringConflictError("宗门洞天内不能采集地表资源")
        location = self._world.locate(LocationQuery(xy=locations[0].xy))
        pool_names = _pool_names(location, mode.resource_category)
        if not pool_names:
            raise GatheringConflictError(f"当前地形没有{mode.resource_category}资源池")

        transitions = []
        total_units = 0
        user_results: dict[str, dict[str, object]] = {}
        source = random.Random(seed)
        public_profiles = {
            value.user_id: value
            for value in await self._character.public_profiles(participants)
        }
        for user_id in participants:
            guard = await self._player_state.authorize(
                user_id, "空闲或托管且可行动"
            )
            if not guard.allowed:
                name = public_profiles.get(user_id)
                raise GatheringConflictError(
                    f"{name.name if name else '有同行修士'}无法开始{mode.kind}：{guard.reason}"
                )
            transitions.append(
                await self._player_state.plan_transition(
                    StateTransitionCommand(
                        user_id=user_id,
                        request_id=request_id,
                        state_type="行为",
                        target_state_id=mode.state_id,
                        context={
                            "采集编号": session_id,
                            "发起者": owner,
                            "参与人数": len(participants),
                        },
                    )
                )
            )
            profile = await self._character.profile(user_id)
            companion_name = await self._assisting_companion_name(user_id)
            unit_count = 1 + int(bool(companion_name))
            total_units += unit_count
            gathering_multiplier = await self._gathering_multiplier(user_id)
            treasure_ratio = 0.0
            activation: InnateTreasureActivation | None = None
            active_treasure = await self._innate_treasure.active(user_id)
            if active_treasure is not None and active_treasure.effect.node == "采集开始":
                effect = active_treasure.effect
                applies = effect.ability == "提高通用采集" or (
                    effect.ability == "提高采药" and mode.kind == "采药"
                ) or (effect.ability == "提高采矿" and mode.kind == "采矿")
                if applies:
                    treasure_ratio = float(effect.values["比例"])
                    activation = InnateTreasureActivation(
                        active_treasure.treasure_id,
                        active_treasure.name,
                        active_treasure.authority,
                        f"{mode.kind}收获提高{treasure_ratio:.0%}，每种最低增加1份",
                    )
            user_results[user_id] = {
                "人物": profile.name,
                "道侣相助": companion_name,
                "采集单位": unit_count,
                "宗门采集倍率": gathering_multiplier,
                "灵宝增益比例": treasure_ratio,
                "先天灵宝": _activation_payload(activation),
                "预定收获": self._precompute_items(
                    mode,
                    pool_names,
                    unit_count,
                    source,
                    gathering_multiplier,
                ),
            }

        place_name = location.location_name or f"{location.region}·{location.terrain}"
        session_value = {
            "玩法": mode.kind,
            "开始请求": request_id,
            "发起者": owner,
            "参与用户": list(participants),
            "地点": place_name,
            "坐标": list(location.xy),
            "地形": location.terrain,
            "资源类别": mode.resource_category,
            "资源池": list(pool_names),
            "采集单位": total_units,
            "每轮秒数": mode.seconds_per_round,
            "最多轮数": mode.maximum_rounds,
            "开始时间": started_at.isoformat(),
            "最晚结束时间": maximum_ends_at.isoformat(),
            "种子": seed,
            "用户结果": user_results,
        }
        operations: list[StateMutation] = [
            StateMutation(owner, SESSION_STATE, session_id, session_value, 0),
            *(plan.mutation for plan in transitions),
        ]
        for user_id in participants:
            previous = await self._database.get(
                StateAddress(user_id, LATEST_STATE, mode.kind)
            )
            operations.append(
                StateMutation(
                    user_id,
                    LATEST_STATE,
                    mode.kind,
                    {"玩法": mode.kind, "发起者": owner, "采集编号": session_id},
                    previous.version if previous else 0,
                )
            )
        try:
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id=owner,
                    request_id=request_id,
                    business_type=f"{mode.kind}开始",
                    operations=tuple(operations),
                    payload={"采集编号": session_id, "参与用户": list(participants)},
                )
            )
        except StateConflictError as exc:
            raise GatheringConflictError(str(exc)) from exc
        return GatheringStarted(
            mode.kind,
            session_id,
            place_name,
            location.terrain,
            len(participants),
            total_units,
            mode.maximum_rounds,
            started_at,
            maximum_ends_at,
            receipt.replayed,
        )

    async def progress(
        self,
        kind: str,
        user_id: str,
        *,
        now: datetime | None = None,
    ) -> GatheringProgress:
        mode = self._mode(kind)
        normalized_user_id = _user_id(user_id)
        owner, session_id, session = await self._session_for(mode, normalized_user_id)
        settlement = await self._database.get(
            StateAddress(owner, SETTLEMENT_STATE, session_id)
        )
        current = _utc(now)
        started = _parse_time(session.get("开始时间"), "采集.开始时间")
        maximum_ends = _parse_time(session.get("最晚结束时间"), "采集.最晚结束时间")
        if settlement is None:
            completed = self._completed_rounds(mode, started, current)
            settled = False
            remaining = max(0, math.ceil((maximum_ends - current).total_seconds()))
        else:
            completed = _nonnegative_int(
                settlement.value.get("完成轮数"), "采集结算.完成轮数"
            )
            settled = True
            remaining = 0
        results = _mapping(session.get("用户结果"), "采集.用户结果")
        own = _mapping(results.get(normalized_user_id), "采集.本人结果")
        own_items = _apply_treasure_bonus(
            _unlocked_items(own.get("预定收获"), completed),
            _ratio(own.get("灵宝增益比例"), "采集.灵宝增益比例"),
        )
        group_quantity = sum(
            item.quantity
            for value in results.values()
            for item in _apply_treasure_bonus(
                _unlocked_items(
                    _mapping(value, "采集.用户结果[]").get("预定收获"), completed
                ),
                _ratio(
                    _mapping(value, "采集.用户结果[]").get("灵宝增益比例"),
                    "采集.灵宝增益比例",
                ),
            )
        )
        return GatheringProgress(
            mode.kind,
            session_id,
            _text(session.get("地点"), "采集.地点"),
            _text(session.get("地形"), "采集.地形"),
            len(_texts(session.get("参与用户"), "采集.参与用户")),
            completed,
            mode.maximum_rounds,
            remaining,
            current >= maximum_ends,
            settled,
            normalized_user_id == owner and not settled,
            group_quantity,
            own_items,
        )

    async def settle(
        self,
        kind: str,
        user_id: str,
        request_id: str,
        *,
        now: datetime | None = None,
    ) -> GatheringSettlement:
        mode = self._mode(kind)
        normalized_user_id = _user_id(user_id)
        owner, session_id, session = await self._session_for(mode, normalized_user_id)
        existing = await self._database.get(
            StateAddress(owner, SETTLEMENT_STATE, session_id)
        )
        if existing is not None:
            return self._settlement(session_id, existing.value, replayed=True)
        if normalized_user_id != owner:
            raise GatheringLeaderRequiredError(f"本次{mode.kind}由领队统一结束")
        settled_at = _utc(now)
        started_at = _parse_time(session.get("开始时间"), "采集.开始时间")
        completed = self._completed_rounds(mode, started_at, settled_at)
        participants = _texts(session.get("参与用户"), "采集.参与用户")
        raw_results = _mapping(session.get("用户结果"), "采集.用户结果")
        operations: list[StateMutation] = []
        summaries: list[dict[str, object]] = []
        for participant in participants:
            raw = _mapping(raw_results.get(participant), f"采集.用户结果.{participant}")
            items = _apply_treasure_bonus(
                _unlocked_items(raw.get("预定收获"), completed),
                _ratio(raw.get("灵宝增益比例"), "采集.灵宝增益比例"),
            )
            inventory = await self._asset.plan_inventory_changes(
                participant,
                tuple(
                    InventoryAdjustment(
                        item.item_id,
                        item.grade_id,
                        item.quantity,
                    )
                    for item in items
                ),
            )
            operations.extend(inventory.operations)
            operations.append(
                (await self._player_state.plan_finish_behavior(participant)).mutation
            )
            summaries.append(
                {
                    "用户": participant,
                    "人物": _text(raw.get("人物"), "采集.人物"),
                    "道侣相助": str(raw.get("道侣相助") or ""),
                    "收获": [
                        {
                            "编号": item.item_id,
                            "品级": item.grade_id,
                            "数量": item.quantity,
                        }
                        for item in items
                    ],
                    "先天灵宝": raw.get("先天灵宝"),
                }
            )
        settlement_value = {
            "玩法": mode.kind,
            "地点": session["地点"],
            "地形": session["地形"],
            "完成轮数": completed,
            "最多轮数": mode.maximum_rounds,
            "参与用户": list(participants),
            "用户结果": summaries,
            "结束时间": settled_at.isoformat(),
        }
        operations.append(
            StateMutation(owner, SETTLEMENT_STATE, session_id, settlement_value, 0)
        )
        try:
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id=owner,
                    request_id=_text(request_id, "request_id"),
                    business_type=f"{mode.kind}结束",
                    operations=tuple(operations),
                    payload={"采集编号": session_id, "完成轮数": completed},
                )
            )
        except StateConflictError as exc:
            raise GatheringConflictError(str(exc)) from exc
        return self._settlement(
            session_id, settlement_value, replayed=receipt.replayed
        )

    async def _assisting_companion_name(self, user_id: str) -> str:
        active = await self._companion.active(user_id)
        if active is None:
            return ""
        instance = await self._companion.instance(user_id, active.companion_id)
        if instance is None:
            raise GatheringStateError("同行道侣缺少实例")
        health = _number(instance.resources.get("血气"), "同行道侣.血气")
        return (
            self._companion.definition(active.companion_id).name if health > 0 else ""
        )

    def _precompute_items(
        self,
        mode: _Mode,
        pool_names: tuple[str, ...],
        unit_count: int,
        source: random.Random,
        multiplier: float = 1.0,
    ) -> list[dict[str, object]]:
        count_per_round = unit_count * mode.draws_per_unit
        draws = self._pool.draw(
            PoolRequest(
                section="物品",
                count=count_per_round * mode.maximum_rounds,
                mode=ALLOW_REPEATS,
                file_ids=pool_names,
                seed=source.getrandbits(64),
            )
        )
        result: list[dict[str, object]] = []
        for index, entry in enumerate(draws.entries):
            record = self._data.entity_record("物品", entry.entity_id)
            if record.number_category != mode.resource_category:
                raise GatheringStateError(
                    f"{mode.kind}资源池混入{record.number_category}：{entry.entity_id}"
                )
            grade = self._asset.draw_drop_grade(seed=source.getrandbits(64))
            quantity = _scaled_quantity(mode.quantity_per_draw, multiplier, source)
            result.append(
                {
                    "轮次": index // count_per_round + 1,
                    "编号": entry.entity_id,
                    "品级": grade.grade_id,
                    "数量": quantity,
                }
            )
        return result

    async def _gathering_multiplier(self, user_id: str) -> float:
        if self._sect is None or self._progress is None:
            return 1.0
        membership = await self._sect.membership(user_id)
        if membership is None:
            return 1.0
        return (await self._progress.snapshot(membership.sect_id)).gathering_multiplier

    def _completed_rounds(
        self, mode: _Mode, started_at: datetime, current: datetime
    ) -> int:
        elapsed = max(0, int((current - started_at).total_seconds()))
        return min(mode.maximum_rounds, elapsed // mode.seconds_per_round)

    async def _start_replay(
        self, mode: _Mode, owner: str, request_id: str
    ) -> GatheringStarted | None:
        latest = await self._database.get(StateAddress(owner, LATEST_STATE, mode.kind))
        if latest is None:
            return None
        value = _mapping(latest.value, f"最近{mode.kind}")
        if _text(value.get("发起者"), f"最近{mode.kind}.发起者") != owner:
            return None
        session_id = _text(value.get("采集编号"), f"最近{mode.kind}.采集编号")
        session = await self._database.get(
            StateAddress(owner, SESSION_STATE, session_id)
        )
        if session is None or session.value.get("开始请求") != request_id:
            return None
        raw = session.value
        return GatheringStarted(
            mode.kind,
            session_id,
            _text(raw.get("地点"), "采集.地点"),
            _text(raw.get("地形"), "采集.地形"),
            len(_texts(raw.get("参与用户"), "采集.参与用户")),
            _positive_int(raw.get("采集单位"), "采集.采集单位"),
            mode.maximum_rounds,
            _parse_time(raw.get("开始时间"), "采集.开始时间"),
            _parse_time(raw.get("最晚结束时间"), "采集.最晚结束时间"),
            True,
        )

    async def _session_for(
        self, mode: _Mode, user_id: str
    ) -> tuple[str, str, Mapping[str, object]]:
        latest = await self._database.get(
            StateAddress(user_id, LATEST_STATE, mode.kind)
        )
        if latest is None:
            raise GatheringStateError(f"当前没有可查看的{mode.kind}")
        value = _mapping(latest.value, f"最近{mode.kind}")
        if _text(value.get("玩法"), f"最近{mode.kind}.玩法") != mode.kind:
            raise GatheringStateError("最近采集玩法与状态键不一致")
        owner = _text(value.get("发起者"), f"最近{mode.kind}.发起者")
        session_id = _text(value.get("采集编号"), f"最近{mode.kind}.采集编号")
        session = await self._database.get(
            StateAddress(owner, SESSION_STATE, session_id)
        )
        if session is None:
            raise GatheringStateError("采集会话不存在")
        if _text(session.value.get("玩法"), "采集.玩法") != mode.kind:
            raise GatheringStateError("采集会话玩法不匹配")
        return owner, session_id, session.value

    def _settlement(
        self,
        session_id: str,
        value: Mapping[str, object],
        *,
        replayed: bool,
    ) -> GatheringSettlement:
        users = tuple(
            _user_summary(_mapping(raw, "采集结算.用户结果[]"))
            for raw in _sequence(value.get("用户结果"), "采集结算.用户结果")
        )
        return GatheringSettlement(
            _text(value.get("玩法"), "采集结算.玩法"),
            session_id,
            _text(value.get("地点"), "采集结算.地点"),
            _text(value.get("地形"), "采集结算.地形"),
            _nonnegative_int(value.get("完成轮数"), "采集结算.完成轮数"),
            _positive_int(value.get("最多轮数"), "采集结算.最多轮数"),
            len(_texts(value.get("参与用户"), "采集结算.参与用户")),
            sum(item.quantity for user in users for item in user.items),
            users,
            _parse_time(value.get("结束时间"), "采集结算.结束时间"),
            replayed,
        )

    def _mode(self, kind: str) -> _Mode:
        self._require_initialized()
        normalized = str(kind or "").strip()
        try:
            return self._modes[normalized]
        except KeyError as exc:
            raise ValueError(f"未知采集玩法：{normalized or '<空>'}") from exc

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("采集核心尚未初始化")


def _parse_mode(kind: str, value: object) -> _Mode:
    rules = _rule_mapping(value, f"规则/玩法/{kind}.json")
    seconds = _rule_positive_int(rules.get("每轮秒数"), f"{kind}.每轮秒数")
    maximum = _rule_positive_int(rules.get("最多轮数"), f"{kind}.最多轮数")
    duration = _rule_positive_int(rules.get("持续秒数"), f"{kind}.持续秒数")
    participants = _rule_positive_int(rules.get("参与用户上限"), f"{kind}.参与用户上限")
    if seconds * maximum != duration:
        raise JsonDataError(f"{kind}持续秒数必须等于每轮秒数乘最多轮数")
    expected = {
        "允许提前结束": True,
        "提前结束轮数": "向下取整",
        "品级来源": "随机奖励",
    }
    if any(
        rules.get(key) != expected_value for key, expected_value in expected.items()
    ):
        raise JsonDataError(f"{kind}提前结束或品级来源不符合采集契约")
    companion = _rule_mapping(rules.get("同行道侣"), f"{kind}.同行道侣")
    if companion != {
        "方式": "相助",
        "每名玩家上限": 1,
        "血气要求": "大于0",
    }:
        raise JsonDataError(f"{kind}同行道侣必须按有血气的一名道侣相助")
    settlement = _rule_mapping(rules.get("结算"), f"{kind}.结算")
    if settlement != {
        "归属": "所属玩家纳戒",
        "时机": "结束时一次写入",
        "参与用户分别结算": True,
    }:
        raise JsonDataError(f"{kind}结算必须分别写入所属玩家纳戒")
    return _Mode(
        kind,
        _rule_text(rules.get("资源类别"), f"{kind}.资源类别"),
        _rule_text(rules.get("行为状态"), f"{kind}.行为状态"),
        seconds,
        maximum,
        duration,
        _rule_positive_int(
            rules.get("每单位每轮抽取次数"), f"{kind}.每单位每轮抽取次数"
        ),
        _rule_positive_int(rules.get("每次物品数量"), f"{kind}.每次物品数量"),
        participants,
    )


def _pool_names(location: LocationView, resource_category: str) -> tuple[str, ...]:
    if resource_category == "灵植":
        return location.plant_pool
    if resource_category == "灵矿":
        return location.mineral_pool
    raise JsonDataError(f"未知采集资源类别：{resource_category}")


def _user_summary(value: Mapping[str, object]) -> GatheringUserSummary:
    return GatheringUserSummary(
        _text(value.get("用户"), "采集结算.用户"),
        _text(value.get("人物"), "采集结算.人物"),
        str(value.get("道侣相助") or ""),
        tuple(
            GatheredItem(
                _text(row.get("编号"), "采集结算.收获.编号"),
                _text(row.get("品级"), "采集结算.收获.品级"),
                _positive_int(row.get("数量"), "采集结算.收获.数量"),
            )
            for row in (
                _mapping(raw, "采集结算.收获[]")
                for raw in _sequence(
                    value.get("收获"), "采集结算.收获", allow_empty=True
                )
            )
        ),
        _payload_activation(value.get("先天灵宝")),
    )


def _unlocked_items(value: object, completed_rounds: int) -> tuple[GatheredItem, ...]:
    totals: dict[tuple[str, str], int] = {}
    for raw in _sequence(value, "采集.预定收获", allow_empty=True):
        row = _mapping(raw, "采集.预定收获[]")
        if _positive_int(row.get("轮次"), "采集.预定收获.轮次") > completed_rounds:
            continue
        key = (
            _text(row.get("编号"), "采集.预定收获.编号"),
            _text(row.get("品级"), "采集.预定收获.品级"),
        )
        totals[key] = totals.get(key, 0) + _positive_int(
            row.get("数量"), "采集.预定收获.数量"
        )
    return tuple(
        GatheredItem(item_id, grade_id, quantity)
        for (item_id, grade_id), quantity in sorted(totals.items())
    )


def _apply_treasure_bonus(
    items: tuple[GatheredItem, ...], ratio: float
) -> tuple[GatheredItem, ...]:
    if ratio <= 0:
        return items
    return tuple(
        GatheredItem(
            item.item_id,
            item.grade_id,
            item.quantity + max(1, math.ceil(item.quantity * ratio)),
        )
        for item in items
    )


def _activation_payload(
    activation: InnateTreasureActivation | None,
) -> dict[str, str] | None:
    if activation is None:
        return None
    return {
        "编号": activation.treasure_id,
        "名称": activation.name,
        "权柄": activation.authority,
        "结果": activation.summary,
    }


def _payload_activation(value: object) -> InnateTreasureActivation | None:
    if value is None:
        return None
    raw = _mapping(value, "采集结算.先天灵宝")
    return InnateTreasureActivation(
        _text(raw.get("编号"), "采集结算.先天灵宝.编号"),
        _text(raw.get("名称"), "采集结算.先天灵宝.名称"),
        _text(raw.get("权柄"), "采集结算.先天灵宝.权柄"),
        _text(raw.get("结果"), "采集结算.先天灵宝.结果"),
    )


def _participants(owner: str, values: tuple[str, ...], maximum: int) -> tuple[str, ...]:
    normalized = tuple(_user_id(value) for value in values) or (owner,)
    if normalized[0] != owner:
        raise ValueError("发起者必须位于参与用户首位")
    if len(normalized) != len(set(normalized)):
        raise ValueError("参与用户不能重复")
    if len(normalized) > maximum:
        raise ValueError(f"一次采集最多{maximum}名用户")
    return normalized


def _stable_seed(kind: str, owner: str, request_id: str) -> int:
    return int.from_bytes(
        hashlib.sha256(f"{kind}\0{owner}\0{request_id}".encode()).digest()[:8]
    )


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("采集时间必须包含时区")
    return current.astimezone(timezone.utc)


def _parse_time(value: object, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value, label))
    except ValueError as exc:
        raise GatheringStateError(f"{label}不是合法时间") from exc
    if parsed.tzinfo is None:
        raise GatheringStateError(f"{label}必须包含时区")
    return parsed.astimezone(timezone.utc)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise GatheringStateError(f"{label}必须是对象")
    return value


def _sequence(
    value: object, label: str, *, allow_empty: bool = False
) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise GatheringStateError(f"{label}必须是数组")
    if not allow_empty and not value:
        raise GatheringStateError(f"{label}不能为空")
    return value


def _texts(value: object, label: str) -> tuple[str, ...]:
    return tuple(_text(raw, f"{label}[]") for raw in _sequence(value, label))


def _text(value: object, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise GatheringStateError(f"{label}不能为空")
    return result


def _user_id(value: object) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError("user_id不能为空")
    return result


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise GatheringStateError(f"{label}必须是正整数")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GatheringStateError(f"{label}必须是非负整数")
    return value


def _number(value: object, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GatheringStateError(f"{label}必须是数值")
    return value


def _ratio(value: object, label: str) -> float:
    number = float(_number(value, label))
    if not 0 <= number <= 1:
        raise GatheringStateError(f"{label}必须在0至1之间")
    return number


def _scaled_quantity(value: int, multiplier: float, source: random.Random) -> int:
    scaled = value * multiplier
    quantity = int(scaled)
    fraction = scaled - quantity
    if fraction and source.random() < fraction:
        quantity += 1
    return max(1, quantity)


def _rule_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return value


def _rule_text(value: object, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise JsonDataError(f"{label}不能为空")
    return result


def _rule_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise JsonDataError(f"{label}必须是正整数")
    return value


__all__ = ["GatheringService"]
