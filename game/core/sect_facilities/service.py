"""解释宗门洞天建筑规则，并原子完成宗门生产。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import wraps
from typing import Any, TypeVar

from game.core.alchemy import AlchemyService
from game.core.asset import (
    AssetEntry,
    AssetService,
    AssetStateError,
    InventoryAdjustment,
)
from game.core.data import (
    JsonDataError,
    JsonDataService,
    mapping as _mapping,
    positive_int as _positive_int,
)
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    SharedConstraintError,
    StateConflictError,
    TransactionCommand,
)
from game.core.forging import ForgingService
from game.core.formation import FormationService
from game.core.location import LocationService
from game.core.sect import SectMember, SectService
from game.core.sect_assets import (
    SectAssetError,
    SectAssetService,
    SectMaterialCost,
    SectProductGain,
)
from game.core.sect_progress import SectProgressService

from .contracts import (
    FacilityPermission,
    SectAlchemyPreview,
    SectCraftResult,
    SectFacility,
    SectFacilityEntry,
    SectFacilityError,
    SectFacilityPage,
    SectFacilityStatus,
    SectForgingPreview,
    SectFormationPreview,
)
from game.core.data import boolean as _bool, nonempty_text as _text

_FACILITY_TYPES = ("炼器", "炼丹", "炼阵")

_T = TypeVar("_T")


def _translate_asset_errors(method: Any) -> Any:
    @wraps(method)
    async def wrapped(*args: object, **kwargs: object) -> _T:
        try:
            return await method(*args, **kwargs)
        except (SectAssetError, AssetStateError) as exc:
            raise SectFacilityError(str(exc)) from exc

    return wrapped


class SectFacilityService:
    """宗门建筑规则与生产事务的唯一核心，城镇设施不经过此核心。"""

    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService | None = None,
        sect: SectService | None = None,
        assets: SectAssetService | None = None,
        asset: AssetService | None = None,
        alchemy: AlchemyService | None = None,
        forging: ForgingService | None = None,
        formation: FormationService | None = None,
        location: LocationService | None = None,
        progress: SectProgressService | None = None,
    ) -> None:
        self._data = data
        self._database = database
        self._sect = sect
        self._sect_assets = assets
        self._asset = asset
        self._alchemy = alchemy
        self._forging = forging
        self._formation = formation
        self._location = location
        self._progress = progress
        self._initialized = False
        self._facilities: dict[str, SectFacility] = {}
        self._permissions: dict[str, FacilityPermission] = {}
        self._base_cost: dict[str, int] = {}
        self._grade_multiplier: dict[str, int] = {}
        self._stage_multiplier: dict[str, int] = {}

    def initialize(self) -> SectFacilityStatus:
        if self._initialized:
            raise RuntimeError("宗门设施核心已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据服务必须先于宗门设施核心启动")
        raw = _mapping(self._data.dataset("宗门规则").get("设施"), "宗门/设施.json")
        buildings = _mapping(raw.get("建筑"), "宗门设施.建筑")
        for facility_type in _FACILITY_TYPES:
            value = _mapping(buildings.get(facility_type), f"宗门设施.建筑.{facility_type}")
            supported = _texts(value.get("支持品级"), f"宗门设施.建筑.{facility_type}.支持品级")
            self._facilities[facility_type] = SectFacility(
                facility_type,
                _text(value.get("名称"), f"宗门设施.建筑.{facility_type}.名称"),
                _text(value.get("范围"), f"宗门设施.建筑.{facility_type}.范围"),
                supported,
            )
        permissions = _mapping(raw.get("身份权限"), "宗门设施.身份权限")
        for role, value in permissions.items():
            item = _mapping(value, f"宗门设施.身份权限.{role}")
            self._permissions[str(role)] = FacilityPermission(
                str(role),
                _bool(item.get("允许个人材料"), f"宗门设施.身份权限.{role}.允许个人材料"),
                _bool(item.get("允许宗门材料"), f"宗门设施.身份权限.{role}.允许宗门材料"),
                _bool(item.get("允许圣品"), f"宗门设施.身份权限.{role}.允许圣品"),
                _bool(item.get("允许发放"), f"宗门设施.身份权限.{role}.允许发放"),
            )
        costs = _mapping(raw.get("灵石消耗"), "宗门设施.灵石消耗")
        base = _mapping(costs.get("基础"), "宗门设施.灵石消耗.基础")
        self._base_cost = {kind: _positive_int(base.get(kind), f"宗门设施.灵石消耗.基础.{kind}") for kind in _FACILITY_TYPES}
        self._grade_multiplier = _positive_map(costs.get("品级倍率"), "宗门设施.灵石消耗.品级倍率")
        self._stage_multiplier = _positive_map(costs.get("器阶倍率"), "宗门设施.灵石消耗.器阶倍率")
        # 炼制失败在提交前中止，语义写在数据里（`结算.失败`），这里读死。
        settlement = _mapping(raw.get("结算"), "宗门设施.结算")
        if settlement.get("失败") != "不扣灵石、不扣材料、不产出":
            raise JsonDataError("宗门设施炼制失败必须不扣灵石、不扣材料、不产出")
        self._initialized = True
        return self.status()

    def status(self) -> SectFacilityStatus:
        return SectFacilityStatus(self._initialized, tuple(self._facilities.values()), tuple(self._permissions))

    def facility(self, facility_type: str) -> SectFacility:
        self._require()
        try:
            return self._facilities[str(facility_type).strip()]
        except KeyError as exc:
            raise SectFacilityError("未知宗门设施") from exc

    def permission(self, role: str) -> FacilityPermission:
        self._require()
        try:
            return self._permissions[str(role).strip()]
        except KeyError as exc:
            raise SectFacilityError("未知宗门身份") from exc

    def cost(self, facility_type: str, grade_or_stage: str) -> int:
        self._require()
        facility = self.facility(facility_type)
        key = str(grade_or_stage or "").strip()
        if key not in facility.supported_grades:
            raise SectFacilityError("该建筑不支持此品级或器阶")
        multiplier = self._stage_multiplier.get(key) if facility_type == "炼器" else self._grade_multiplier.get(key)
        if multiplier is None:
            raise SectFacilityError("设施消耗规则缺少对应品级或器阶")
        return self._base_cost[facility_type] * multiplier

    def authorize(self, role: str, material_source: str, grade_or_stage: str) -> FacilityPermission:
        permission = self.permission(role)
        if material_source == "个人纳戒" and not permission.personal_materials:
            raise SectFacilityError("当前身份不能使用个人材料炼制")
        if material_source == "宗门灵藏" and not permission.sect_materials:
            raise SectFacilityError("当前身份不能调用宗门灵藏材料")
        if material_source not in {"个人纳戒", "宗门灵藏"}:
            raise SectFacilityError("材料来源必须是个人纳戒或宗门灵藏")
        if grade_or_stage == "圣品" and not permission.sacred_grade:
            raise SectFacilityError("当前身份不能炼制圣品")
        return permission

    async def in_cave(self, user_id: str) -> bool:
        self._require_runtime()
        member = await self._sect.membership(user_id)
        if member is None:
            return False
        sect = await self._sect.sect(member.sect_id)
        current = await self._location.current(user_id)
        return (
            sect is not None
            and current.space_type == "宗门洞天"
            and current.space_id == sect.cave_id
        )

    async def forging_page(
        self, user_id: str, material_source: str, stage: str = "", page: int = 1
    ) -> SectFacilityPage:
        member, entries, stones = await self._context(user_id, material_source)
        facility = self.facility("炼器")
        if not stage:
            values = tuple(
                SectFacilityEntry(
                    name,
                    name,
                    f"{len(self._forging.laws(name))}道器律",
                    True,
                )
                for name in ("灵器", "法器", "法宝", "后天灵宝")
            )
            return SectFacilityPage(
                facility, member.role, material_source, stones, "总览", values
            )
        laws = self._forging.laws(stage)
        current, total, selected = _paginate(laws, page, 20)
        values = tuple(
            SectFacilityEntry(
                law.law_id,
                law.name,
                law.method,
                self._forging.assess(law.law_id, entries).can_forge,
            )
            for law in selected
        )
        return SectFacilityPage(
            facility,
            member.role,
            material_source,
            stones,
            stage,
            values,
            current,
            total,
        )

    async def alchemy_page(
        self, user_id: str, material_source: str, category: str = "", page: int = 1
    ) -> SectFacilityPage:
        member, entries, stones = await self._context(user_id, material_source)
        facility = self.facility("炼丹")
        if not category:
            values = tuple(
                SectFacilityEntry(
                    name,
                    name,
                    f"{len(self._alchemy.recipes(name))}种丹药",
                    True,
                )
                for name in ("恢复丹", "战丹", "突破丹", "特殊丹")
            )
            return SectFacilityPage(
                facility, member.role, material_source, stones, "总览", values
            )
        recipes = self._alchemy.recipes(category)
        current, total, selected = _paginate(recipes, page, 20)
        values = tuple(
            SectFacilityEntry(
                recipe.recipe_id,
                recipe.medicine_name,
                f"难度{recipe.difficulty} · {recipe.method}",
                self._alchemy.assess(recipe.recipe_id, entries).can_refine,
            )
            for recipe in selected
        )
        return SectFacilityPage(
            facility,
            member.role,
            material_source,
            stones,
            category,
            values,
            current,
            total,
        )

    async def formation_page(
        self, user_id: str, material_source: str, page: int = 1
    ) -> SectFacilityPage:
        member, _, stones = await self._context(user_id, material_source)
        facility = self.facility("炼阵")
        current, total, selected = _paginate(self._formation.formations(), page, 20)
        values = tuple(
            SectFacilityEntry(
                formation.formation_id,
                formation.name,
                formation.core,
                True,
            )
            for formation in selected
        )
        return SectFacilityPage(
            facility,
            member.role,
            material_source,
            stones,
            "阵法",
            values,
            current,
            total,
        )

    async def preview_forging(
        self, user_id: str, identifier: str, material_source: str
    ) -> SectForgingPreview:
        member, entries, stones = await self._context(user_id, material_source)
        assessment = self._forging.assess(identifier, entries)
        self.authorize(member.role, material_source, assessment.law.stage)
        cost = self.cost("炼器", assessment.law.stage)
        if material_source == "宗门灵藏":
            cost = await self._discounted_cost(member.sect_id, cost)
        return SectForgingPreview(
            self.facility("炼器"),
            member.role,
            material_source,
            stones,
            cost,
            assessment,
        )

    async def preview_alchemy(
        self, user_id: str, identifier: str, material_source: str
    ) -> SectAlchemyPreview:
        member, entries, stones = await self._context(user_id, material_source)
        assessment = self._alchemy.assess(identifier, entries)
        self.authorize(member.role, material_source, assessment.medicine_grade_name)
        cost = self.cost("炼丹", assessment.medicine_grade_name)
        if material_source == "宗门灵藏":
            cost = await self._discounted_cost(member.sect_id, cost)
        return SectAlchemyPreview(
            self.facility("炼丹"),
            member.role,
            material_source,
            stones,
            cost,
            assessment,
        )

    async def preview_formation(
        self,
        user_id: str,
        identifier: str,
        grade: str,
        material_source: str,
        investments: Mapping[str, int] | None = None,
    ) -> SectFormationPreview:
        member, entries, stones = await self._context(user_id, material_source)
        assessment = self._formation.assess(identifier, grade, entries, investments)
        grade_key = f"{assessment.grade_name}品"
        self.authorize(member.role, material_source, grade_key)
        cost = self.cost("炼阵", grade_key)
        if grade_key == "圣品":
            cost += sum(item.required for item in assessment.requirements) * 1_000
        if material_source == "宗门灵藏":
            cost = await self._discounted_cost(member.sect_id, cost)
        return SectFormationPreview(
            self.facility("炼阵"),
            member.role,
            material_source,
            stones,
            cost,
            assessment,
        )

    async def _discounted_cost(self, sect_id: str, cost: int) -> int:
        if self._progress is None:
            return cost
        snapshot = await self._progress.snapshot(sect_id)
        return max(1, int(cost * snapshot.facility_cost_multiplier))

    @_translate_asset_errors
    async def forge(
        self, user_id: str, request_id: str, identifier: str, material_source: str
    ) -> SectCraftResult:
        member = await self._member_in_cave(user_id)
        replay = await self._replay(user_id, request_id, "宗门炼器", identifier, material_source)
        if replay is not None:
            return replay
        preview = await self.preview_forging(user_id, identifier, material_source)
        if not preview.assessment.can_forge:
            raise SectFacilityError("兽宝和灵矿不足以炼成该器律")
        materials = preview.assessment.beast_materials + preview.assessment.mineral_materials
        public = await self._sect_assets.plan_production(
            member.sect_id,
            preview.spirit_stone_cost,
            materials=(
                tuple(
                    SectMaterialCost("兽宝", item.item_id, item.grade_id, item.quantity)
                    for item in preview.assessment.beast_materials
                )
                + tuple(
                    SectMaterialCost("灵矿", item.item_id, item.grade_id, item.quantity)
                    for item in preview.assessment.mineral_materials
                )
                if material_source == "宗门灵藏"
                else ()
            ),
            product=(
                SectProductGain("器律", preview.assessment.law.law_id)
                if material_source == "宗门灵藏"
                else None
            ),
        )
        operations = list(public.operations)
        destination = "万珍殿"
        if material_source == "个人纳戒":
            inventory = await self._asset.plan_inventory_changes(
                user_id,
                tuple(
                    InventoryAdjustment(item.item_id, item.grade_id, -item.quantity)
                    for item in materials
                ),
            )
            reserve = await self._asset.plan_law_reserve_acquisition(
                user_id, preview.assessment.law.law_id
            )
            operations = [*inventory.operations, reserve.operation, *operations]
            destination = "器藏"
        payload = _payload(
            preview.facility,
            material_source,
            preview.assessment.law.law_id,
            preview.assessment.law.name,
            preview.assessment.law.stage,
            destination,
            preview.spirit_stone_cost,
            public.spirit_stones_after,
        )
        replayed = await self._commit(user_id, request_id, "宗门炼器", operations, payload)
        return _result(preview.facility, payload, replayed)

    @_translate_asset_errors
    async def refine(
        self, user_id: str, request_id: str, identifier: str, material_source: str
    ) -> SectCraftResult:
        member = await self._member_in_cave(user_id)
        replay = await self._replay(user_id, request_id, "宗门炼丹", identifier, material_source)
        if replay is not None:
            return replay
        preview = await self.preview_alchemy(user_id, identifier, material_source)
        assessment = preview.assessment
        if not assessment.can_refine or assessment.beast_material is None:
            raise SectFacilityError("兽宝和灵植不足以炼成该丹药")
        materials = (assessment.beast_material,) + assessment.herb_materials
        public = await self._sect_assets.plan_production(
            member.sect_id,
            preview.spirit_stone_cost,
            materials=(
                (
                    SectMaterialCost(
                        "兽宝",
                        assessment.beast_material.item_id,
                        assessment.beast_material.grade_id,
                        assessment.beast_material.quantity,
                    ),
                )
                + tuple(
                    SectMaterialCost("灵植", item.item_id, item.grade_id, item.quantity)
                    for item in assessment.herb_materials
                )
                if material_source == "宗门灵藏"
                else ()
            ),
            product=(
                SectProductGain(
                    "丹药",
                    assessment.recipe.medicine_id,
                    assessment.medicine_grade_id,
                )
                if material_source == "宗门灵藏"
                else None
            ),
        )
        operations = list(public.operations)
        destination = "万珍殿"
        if material_source == "个人纳戒":
            inventory = await self._asset.plan_inventory_changes(
                user_id,
                tuple(
                    InventoryAdjustment(item.item_id, item.grade_id, -item.quantity)
                    for item in materials
                )
                + (
                    InventoryAdjustment(
                        assessment.recipe.medicine_id,
                        assessment.medicine_grade_id,
                        1,
                    ),
                ),
            )
            operations = [*inventory.operations, *operations]
            destination = "纳戒"
        payload = _payload(
            preview.facility,
            material_source,
            assessment.recipe.recipe_id,
            assessment.recipe.medicine_name,
            assessment.medicine_grade_name,
            destination,
            preview.spirit_stone_cost,
            public.spirit_stones_after,
        )
        payload["产出编号"] = assessment.recipe.medicine_id
        replayed = await self._commit(user_id, request_id, "宗门炼丹", operations, payload)
        return _result(preview.facility, payload, replayed)

    @_translate_asset_errors
    async def form(
        self,
        user_id: str,
        request_id: str,
        identifier: str,
        grade: str,
        material_source: str,
        investments: Mapping[str, int] | None = None,
    ) -> SectCraftResult:
        member = await self._member_in_cave(user_id)
        request_key = f"{identifier}:{grade}"
        replay = await self._replay(user_id, request_id, "宗门炼阵", request_key, material_source)
        if replay is not None:
            return replay
        preview = await self.preview_formation(
            user_id, identifier, grade, material_source, investments
        )
        assessment = preview.assessment
        if not assessment.can_form:
            raise SectFacilityError("兽宝、灵矿和灵植不足以炼成该阵法")
        actual = tuple((item.category, item.required) for item in assessment.requirements)
        public = await self._sect_assets.plan_production(
            member.sect_id,
            preview.spirit_stone_cost,
            materials=(
                tuple(
                    SectMaterialCost(
                        item.category,
                        item.item_id,
                        item.grade_id,
                        item.quantity,
                    )
                    for item in assessment.materials
                )
                if material_source == "宗门灵藏"
                else ()
            ),
            product=(
                SectProductGain(
                    "阵法",
                    assessment.formation.formation_id,
                    assessment.grade_id,
                    materials=actual if assessment.grade_id == "05" else (),
                    instance_key=request_id if assessment.grade_id == "05" else "",
                )
                if material_source == "宗门灵藏"
                else None
            ),
        )
        operations = list(public.operations)
        destination = "万珍殿"
        if material_source == "个人纳戒":
            inventory = await self._asset.plan_inventory_changes(
                user_id,
                tuple(
                    InventoryAdjustment(item.item_id, item.grade_id, -item.quantity)
                    for item in assessment.materials
                ),
            )
            reserve = await self._asset.plan_formation_reserve_acquisition(
                user_id,
                assessment.formation.formation_id,
                assessment.grade_id,
                materials=(
                    {key: str(value) for key, value in actual}
                    if assessment.grade_id == "05"
                    else None
                ),
            )
            operations = [*inventory.operations, reserve.operation, *operations]
            destination = "阵藏"
        payload = _payload(
            preview.facility,
            material_source,
            request_key,
            assessment.formation.name,
            f"{assessment.grade_name}品",
            destination,
            preview.spirit_stone_cost,
            public.spirit_stones_after,
        )
        payload["产出编号"] = assessment.formation.formation_id
        replayed = await self._commit(user_id, request_id, "宗门炼阵", operations, payload)
        return _result(preview.facility, payload, replayed)

    async def _context(
        self, user_id: str, material_source: str
    ) -> tuple[SectMember, tuple[AssetEntry, ...], int]:
        member = await self._member_in_cave(user_id)
        self.authorize(member.role, material_source, "")
        vault = await self._sect_assets.lingcang(user_id)
        if material_source == "个人纳戒":
            snapshot = await self._asset.snapshot(user_id)
            entries = tuple(
                item
                for item in snapshot.entries
                if item.category == "基础物品"
                and item.subcategory in {"兽宝", "灵植", "灵矿"}
            )
        else:
            entries = tuple(
                AssetEntry(
                    "基础物品",
                    item.category,
                    item.content_id,
                    item.entry_key,
                    item.name,
                    item.grade_id,
                    item.grade_name,
                    item.quantity,
                )
                for item in vault.entries
                if item.category in {"兽宝", "灵植", "灵矿"}
            )
        return member, entries, vault.spirit_stones

    async def _member_in_cave(self, user_id: str):
        self._require_runtime()
        member = await self._sect.membership(user_id)
        if member is None:
            raise SectFacilityError("尚未加入宗门")
        sect = await self._sect.sect(member.sect_id)
        current = await self._location.current(user_id)
        if (
            sect is None
            or current.space_type != "宗门洞天"
            or current.space_id != sect.cave_id
        ):
            raise SectFacilityError("只有身处本宗洞天时才能使用宗门设施")
        return member

    async def _replay(
        self,
        user_id: str,
        request_id: str,
        business_type: str,
        request_key: str,
        material_source: str,
    ) -> SectCraftResult | None:
        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is None:
            return None
        payload = committed.payload
        if (
            committed.receipt.business_type != business_type
            or payload.get("请求") != request_key
            or payload.get("材料来源") != material_source
        ):
            raise SectFacilityError("请求编号已经用于其他操作")
        return _result(self.facility(str(payload.get("设施类型") or "")), payload, True)

    async def _commit(
        self,
        user_id: str,
        request_id: str,
        business_type: str,
        operations: Sequence[object],
        payload: dict[str, object],
    ) -> bool:
        try:
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id,
                    str(request_id or "").strip(),
                    business_type,
                    tuple(operations),
                    payload,
                )
            )
        except IdempotencyConflictError as exc:
            raise SectFacilityError("请求编号已经用于其他操作") from exc
        except (StateConflictError, SharedConstraintError) as exc:
            raise SectFacilityError("宗门或个人资产刚刚发生变化，请重新审材") from exc
        except (SectAssetError, AssetStateError) as exc:
            raise SectFacilityError(str(exc)) from exc
        return receipt.replayed

    def _require_runtime(self) -> None:
        self._require()
        if any(
            value is None
            for value in (
                self._database,
                self._sect,
                self._sect_assets,
                self._asset,
                self._alchemy,
                self._forging,
                self._formation,
                self._location,
            )
        ):
            raise RuntimeError("宗门设施核心没有装配生产依赖")

    def _require(self) -> None:
        if not self._initialized:
            raise RuntimeError("宗门设施核心尚未初始化")


def _texts(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value or any(not str(item).strip() for item in value):
        raise JsonDataError(f"{label}必须是非空字符串列表")
    return tuple(str(item).strip() for item in value)


def _positive_map(value: object, label: str) -> dict[str, int]:
    raw = _mapping(value, label)
    return {str(key): _positive_int(item, f"{label}.{key}") for key, item in raw.items()}


def _paginate(values: Sequence, page: int, page_size: int):
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise SectFacilityError("页码必须是正整数")
    page_count = max(1, (len(values) + page_size - 1) // page_size)
    if page > page_count:
        raise SectFacilityError(f"页码超出范围：1至{page_count}")
    start = (page - 1) * page_size
    return page, page_count, values[start : start + page_size]


def _payload(
    facility: SectFacility,
    material_source: str,
    request_key: str,
    product_name: str,
    grade_or_stage: str,
    destination: str,
    cost: int,
    stones_after: int,
) -> dict[str, object]:
    return {
        "设施类型": facility.facility_type,
        "设施名称": facility.name,
        "材料来源": material_source,
        "请求": request_key,
        "产出编号": request_key,
        "产出名称": product_name,
        "品级或器阶": grade_or_stage,
        "产出去向": destination,
        "灵石消耗": cost,
        "宗门灵石余量": stones_after,
    }


def _result(
    facility: SectFacility, payload: Mapping[str, object], replayed: bool
) -> SectCraftResult:
    return SectCraftResult(
        facility,
        str(payload.get("材料来源") or ""),
        str(payload.get("产出编号") or ""),
        str(payload.get("产出名称") or ""),
        str(payload.get("品级或器阶") or ""),
        str(payload.get("产出去向") or ""),
        int(payload.get("灵石消耗") or 0),
        int(payload.get("宗门灵石余量") or 0),
        replayed,
    )


__all__ = ["SectFacilityService"]
