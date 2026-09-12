"""解释宗门资源生产 JSON，并原子结算灵脉与灵田产出。"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from types import MappingProxyType

from game.core.asset import AssetService
from game.core.data import (
    JsonDataError,
    JsonDataService,
    mapping as _mapping,
    nonempty_text as _text,
    nonnegative_int,
    positive_int as _positive_int,
)
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    SharedConstraintError,
    SharedEntityMutation,
    StateConflictError,
    TransactionCommand,
)
from game.core.location import LocationService
from game.core.pool import PoolService
from game.core.sect import SectService
from game.core.sect_assets import SectAssetError, SectAssetService, SectMaterialCost
from game.core.sect_progress import SectProgressService

from .contracts import (
    SectProductionError,
    SectProductionFacility,
    SectProductionOutput,
    SectProductionResult,
    SectProductionStatus,
    SectProductionView,
)

_FACILITY_TYPES = ("灵脉", "灵田")
_ENTITY_TYPES = {"灵脉": "宗门灵脉", "灵田": "宗门灵田"}


class SectProductionService:
    """宗门资源设施的唯一生产核心。"""

    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService,
        sect: SectService,
        assets: SectAssetService,
        asset: AssetService,
        pool: PoolService,
        location: LocationService,
        progress: SectProgressService | None = None,
    ) -> None:
        self._data = data
        self._database = database
        self._sect = sect
        self._assets = assets
        self._asset = asset
        self._pool = pool
        self._location = location
        self._progress = progress
        self._initialized = False
        self._facilities: Mapping[str, SectProductionFacility] = MappingProxyType({})
        self._rule_version = ""

    def initialize(self) -> SectProductionStatus:
        if self._initialized:
            raise RuntimeError("宗门资源生产核心已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据微服务必须先于宗门资源生产核心启动")
        raw = _mapping(self._data.dataset("宗门规则").get("生产"), "宗门生产")
        self._rule_version = _text(raw.get("规则版本"), "宗门生产.规则版本")
        period = _positive_int(raw.get("周期秒"), "宗门生产.周期秒")
        catch_up = _positive_int(raw.get("累计轮数上限"), "宗门生产.累计轮数上限")
        multiplier = _positive_float(raw.get("基础产量倍率"), "宗门生产.基础产量倍率")
        facilities = _mapping(raw.get("设施"), "宗门生产.设施")
        outputs = _mapping(raw.get("产出"), "宗门生产.产出")
        loaded: dict[str, SectProductionFacility] = {}
        for kind in _FACILITY_TYPES:
            value = _mapping(facilities.get(kind), f"宗门生产.设施.{kind}")
            if _text(value.get("名称"), f"宗门生产.设施.{kind}.名称") != kind:
                raise JsonDataError(f"宗门生产设施名称必须为{kind}")
            output = _mapping(outputs.get(kind), f"宗门生产.产出.{kind}")
            primary_key = "灵石范围" if kind == "灵脉" else "灵植数量"
            material_key = "灵矿数量" if kind == "灵脉" else "灵植数量"
            loaded[kind] = SectProductionFacility(
                kind,
                kind,
                period,
                catch_up,
                multiplier,
                _range(output.get(primary_key), f"宗门生产.产出.{kind}.{primary_key}"),
                _range(
                    output.get(material_key), f"宗门生产.产出.{kind}.{material_key}"
                ),
            )
        self._facilities = MappingProxyType(loaded)
        self._validate_outputs(raw, loaded)
        self._initialized = True
        return self.status()

    def status(self) -> SectProductionStatus:
        return SectProductionStatus(self._initialized, tuple(self._facilities.values()))

    async def view(
        self, kind: str, user_id: str, *, now: datetime | None = None
    ) -> SectProductionView:
        member, facility = await self._context(kind, user_id, officer=False)
        current = _utc(now)
        record = await self._database.get_shared_entity(
            _ENTITY_TYPES[facility.kind], member.sect_id
        )
        return self._view_from_record(facility, member.role, record, current)

    async def collect(
        self,
        kind: str,
        user_id: str,
        request_id: str,
        *,
        now: datetime | None = None,
    ) -> SectProductionResult:
        member, facility = await self._context(kind, user_id, officer=True)
        current = _utc(now)
        entity_type = _ENTITY_TYPES[facility.kind]
        record = await self._database.get_shared_entity(entity_type, member.sect_id)
        if record is None:
            baseline = _state_value(
                member.sect_id, facility.kind, current, self._rule_version
            )
            try:
                receipt = await self._database.commit(
                    TransactionCommand(
                        user_id,
                        _request(request_id),
                        f"{facility.kind}初始化",
                        (
                            SharedEntityMutation(
                                entity_type, member.sect_id, baseline, 0
                            ),
                        ),
                        {
                            "宗门编号": member.sect_id,
                            "设施": facility.kind,
                            "初始化": True,
                        },
                    )
                )
            except (
                SharedConstraintError,
                StateConflictError,
                IdempotencyConflictError,
            ) as exc:
                raise SectProductionError(
                    "宗门资源生产状态刚刚发生变化，请重试"
                ) from exc
            view = SectProductionView(
                facility,
                member.role,
                self._sect.is_officer(member.role),
                True,
                current,
                0,
                facility.period_seconds,
            )
            return SectProductionResult(view, True, 0, (), 0, 0, receipt.replayed)
        value = _mapping(record.value, entity_type)
        last = _time(value.get("上次结算时间"), f"{entity_type}.上次结算时间")
        sequence = _nonnegative_int(value.get("结算序号"), f"{entity_type}.结算序号")
        cycles = min(
            facility.catch_up_limit,
            max(0, int((current - last).total_seconds() // facility.period_seconds)),
        )
        if cycles == 0:
            view = self._view_from_record(facility, member.role, record, current)
            return SectProductionResult(view, False, 0, (), 0, 0, False)
        multiplier = 1.0
        if self._progress is not None:
            multiplier = (
                await self._progress.snapshot(member.sect_id)
            ).production_multiplier
        outputs, spirit_stones = self._roll(
            facility, member.sect_id, sequence, cycles, multiplier
        )
        gain = await self._assets.plan_resource_gain(
            member.sect_id,
            spirit_stones,
            tuple(
                SectMaterialCost(
                    item.category, item.content_id, item.grade_id, item.quantity
                )
                for item in outputs
                if item.category != "灵石"
            ),
        )
        settled_at = last + timedelta(seconds=cycles * facility.period_seconds)
        next_value = _state_value(
            member.sect_id,
            facility.kind,
            settled_at,
            self._rule_version,
            sequence=sequence + cycles,
        )
        operations = (
            *gain.operations,
            SharedEntityMutation(
                entity_type, member.sect_id, next_value, record.version
            ),
        )
        payload = {
            "宗门编号": member.sect_id,
            "设施": facility.kind,
            "轮数": cycles,
            "产出": [
                {
                    "类别": item.category,
                    "编号": item.content_id,
                    "品级": item.grade_id,
                    "数量": item.quantity,
                }
                for item in outputs
            ],
            "灵石": spirit_stones,
            "结算序号": sequence + cycles,
            "规则版本": self._rule_version,
        }
        try:
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id,
                    _request(request_id),
                    f"{facility.kind}收取",
                    tuple(operations),
                    payload,
                )
            )
        except IdempotencyConflictError as exc:
            raise SectProductionError("请求编号已经用于其他操作") from exc
        except (StateConflictError, SharedConstraintError, SectAssetError) as exc:
            raise SectProductionError("宗门资源刚刚发生变化，请重新收取") from exc
        after = self._view_from_values(facility, member.role, next_value, current)
        return SectProductionResult(
            after,
            False,
            cycles,
            outputs,
            spirit_stones,
            gain.spirit_stones_after,
            receipt.replayed,
        )

    async def _context(self, kind: str, user_id: str, *, officer: bool):
        self._require()
        normalized_kind = str(kind or "").strip()
        facility = self._facilities.get(normalized_kind)
        if facility is None:
            raise SectProductionError("未知宗门资源设施")
        member = await self._sect.membership(user_id)
        if member is None:
            raise SectProductionError("尚未加入宗门")
        if officer and not self._sect.is_officer(member.role):
            raise SectProductionError("只有宗主和长老可以收取宗门资源")
        sect = await self._sect.sect(member.sect_id)
        current = await self._location.current(user_id)
        if (
            sect is None
            or current.space_type != "宗门洞天"
            or current.space_id != sect.cave_id
        ):
            raise SectProductionError("只有身处本宗洞天时才能使用资源设施")
        return member, facility

    def _roll(
        self,
        facility: SectProductionFacility,
        sect_id: str,
        sequence: int,
        cycles: int,
        multiplier: float = 1.0,
    ) -> tuple[tuple[SectProductionOutput, ...], int]:
        totals: dict[tuple[str, str, str], int] = {}
        stones = 0
        for offset in range(cycles):
            cycle = sequence + offset
            seed = _seed(self._rule_version, sect_id, facility.kind, cycle)
            rng = random.Random(seed)
            if facility.kind == "灵脉":
                stones += _scaled_quantity(
                    rng.randint(*facility.primary_range) * facility.base_multiplier,
                    multiplier,
                    rng,
                )
                category = "灵矿"
                quantity = _scaled_quantity(
                    rng.randint(*facility.material_range) * facility.base_multiplier,
                    multiplier,
                    rng,
                )
            else:
                category = "灵植"
                quantity = _scaled_quantity(
                    rng.randint(*facility.material_range) * facility.base_multiplier,
                    multiplier,
                    rng,
                )
            item_id = self._pool.draw_item_category(category, seed=seed ^ 0xA5A5A5A5)[0]
            grade = self._asset.draw_drop_grade(seed=seed ^ 0x5A5A5A5A)
            key = (category, item_id, grade.grade_id)
            totals[key] = totals.get(key, 0) + quantity
        outputs = tuple(
            SectProductionOutput(
                category,
                content_id,
                _entity_name(self._data, content_id),
                grade_id,
                self._asset.grade(grade_id).name,
                quantity,
            )
            for (category, content_id, grade_id), quantity in sorted(totals.items())
        )
        return outputs, stones

    def _view_from_record(self, facility, role, record, current):
        if record is None:
            return SectProductionView(
                facility,
                role,
                self._sect.is_officer(role),
                False,
                None,
                0,
                facility.period_seconds,
            )
        return self._view_from_values(facility, role, record.value, current)

    def _view_from_values(self, facility, role, value, current):
        last = _time(value.get("上次结算时间"), f"{facility.kind}.上次结算时间")
        pending = min(
            facility.catch_up_limit,
            max(0, int((current - last).total_seconds() // facility.period_seconds)),
        )
        elapsed = max(0, int((current - last).total_seconds()))
        remaining = facility.period_seconds - (elapsed % facility.period_seconds)
        return SectProductionView(
            facility,
            role,
            self._sect.is_officer(role),
            True,
            last,
            pending,
            remaining,
        )

    def _validate_outputs(self, raw, facilities) -> None:
        outputs = _mapping(raw.get("产出"), "宗门生产.产出")
        for kind in _FACILITY_TYPES:
            value = _mapping(outputs.get(kind), f"宗门生产.产出.{kind}")
            if kind == "灵脉" and _texts(
                value.get("类别"), f"宗门生产.产出.{kind}.类别"
            ) != ("灵石", "灵矿"):
                raise JsonDataError("灵脉产出必须是灵石和灵矿")
            if kind == "灵田" and _texts(
                value.get("类别"), f"宗门生产.产出.{kind}.类别"
            ) != ("灵植",):
                raise JsonDataError("灵田产出必须是灵植")

    def _require(self):
        if not self._initialized:
            raise RuntimeError("宗门资源生产核心尚未初始化")


def _state_value(sect_id, kind, settled_at, version, *, sequence=0):
    return {
        "名称": kind,
        "宗门编号": sect_id,
        "设施": kind,
        "上次结算时间": settled_at.isoformat(),
        "结算序号": sequence,
        "规则版本": version,
    }


def _seed(version, sect_id, kind, sequence):
    raw = f"{version}|{sect_id}|{kind}|{sequence}".encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def _utc(value):
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        return result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _time(value, label):
    try:
        result = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise SectProductionError(f"{label}格式错误") from exc
    return _utc(result)


def _texts(value, label):
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError(f"{label}必须是字符串数组")
    return tuple(_text(item, label) for item in value)


def _nonnegative_int(value, label):
    return nonnegative_int(value, label, error=SectProductionError)


def _positive_float(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise JsonDataError(f"{label}必须是正数")
    return float(value)


def _scaled_quantity(value: float, multiplier: float, source: random.Random) -> int:
    scaled = float(value) * multiplier
    quantity = int(scaled)
    fraction = scaled - quantity
    if fraction and source.random() < fraction:
        quantity += 1
    return max(1, quantity)


def _range(value, label):
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
        or value[0] < 1
        or value[1] < value[0]
    ):
        raise JsonDataError(f"{label}必须是正整数范围")
    return int(value[0]), int(value[1])


def _request(value):
    result = str(value or "").strip()
    if not result:
        raise SectProductionError("请求编号不能为空")
    return result


def _entity_name(data, content_id):
    value = data.entity("基础物品", content_id)
    name = str(value.get("名称") or "").strip()
    if not name:
        raise SectProductionError(f"物品缺少名称：{content_id}")
    return name


__all__ = ["SectProductionService"]
