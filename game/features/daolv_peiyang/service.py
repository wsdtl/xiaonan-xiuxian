"""当前同行道侣培养的事务编排。"""

from __future__ import annotations

from game.core.item_catalog import ItemDetail, ItemCatalogError, ItemCatalogService

from game.core.asset import (
    InventoryStack,
    AssetService,
    AssetStateError,
    InventoryAdjustment,
    InventoryChangeError,
)

from collections.abc import Mapping

from game.core.companion import (
    CompanionCultivationError,
    CompanionService,
    CompanionStateError,
)
from game.core.data import JsonDataError, JsonDataService
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    StateConflictError,
    TransactionCommand,
)
from game.core.forging import ForgingService
from game.core.growth import GrowthService
from game.features.presentation import require_mapping

from .contracts import (
    CompanionBreakthroughRequest,
    CompanionBreakthroughResult,
    CompanionCultivationConflictError,
    CompanionCultivationFeatureError,
    CompanionCultivationView,
    CompanionLawRequest,
    CompanionLawResult,
)


class CompanionCultivationFeature:
    """只操作当前同行道侣；不提供功法、真意和气机手动装配。"""

    def __init__(
        self,
        data: JsonDataService,
        companion: CompanionService,
        assets: AssetService,
        items: ItemCatalogService,
        growth: GrowthService,
        forging: ForgingService,
        database: DatabaseService,
    ) -> None:
        self._data = data
        self._companion = companion
        self._assets = assets
        self._items = items
        self._growth = growth
        self._forging = forging
        self._database = database
        self._initialized = False
        self._copy: Mapping[str, object] = {}

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("道侣培养玩法微服务已经初始化")
        for ready, label in (
            (self._companion.status().initialized, "道侣核心"),
            (self._assets.status().initialized, "资产核心"),
            (self._items.status().initialized, "物品核心"),
            (self._growth.status().initialized, "成长核心"),
            (self._forging.status().initialized, "炼器核心"),
            (self._database.status().initialized, "数据库核心"),
        ):
            if not ready:
                raise RuntimeError(f"{label}必须先于道侣培养玩法启动")
        dataset = self._data.dataset("培养展示")
        self._copy = require_mapping(dataset.get("文本"), "玩法/培养/展示/文本.json")
        require_mapping(self._copy.get("道侣"), "培养文本.道侣")
        require_mapping(self._copy.get("突破"), "培养文本.突破")
        require_mapping(self._copy.get("覆炼"), "培养文本.覆炼")
        self._initialized = True

    def copy(self, section: str, key: str) -> str:
        self._require_initialized()
        value = require_mapping(self._copy.get(section), f"培养文本.{section}").get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"培养展示缺少文本：{section}.{key}")
        return value.strip()

    async def inspect(self, user_id: str) -> CompanionCultivationView:
        self._require_initialized()
        try:
            active = await self._companion.active_instance(user_id)
            definition = self._companion.definition(active.instance.companion_id)
            realm = self._growth.realm(active.instance.realm_id)
            weapon_stage_definition = self._forging.weapon_stage(
                active.instance.weapon_level
            )
            weapon_stage = weapon_stage_definition.name
            open_law_slots = weapon_stage_definition.open_law_slots
            return CompanionCultivationView(
                definition,
                active.instance,
                realm.name,
                weapon_stage,
                open_law_slots,
                tuple(
                    (
                        category,
                        tuple(
                            str(self._data.entity(category, content_id).get("名称"))
                            for content_id in content_ids
                        ),
                    )
                    for category, content_ids in active.instance.cultivation.items()
                ),
                tuple(
                    (
                        slot,
                        str(self._data.entity("器律", law_id).get("名称")),
                    )
                    for slot, law_id in enumerate(active.instance.weapon_laws, start=1)
                    if law_id is not None
                ),
                self._growth.experience_required(active.instance.level),
                self._forging.weapon_experience_required(active.instance.weapon_level),
            )
        except (CompanionStateError, CompanionCultivationError, ValueError) as exc:
            raise CompanionCultivationFeatureError(str(exc)) from exc

    async def breakthrough(
        self, request: CompanionBreakthroughRequest
    ) -> CompanionBreakthroughResult:
        self._require_initialized()
        medicine = self._resolve_item(request.medicine, "丹药")
        try:
            stack = await self._lowest_inventory_stack(
                request.user_id, medicine.item_id
            )
            plan = await self._companion.plan_breakthrough(
                request.user_id, medicine_id=medicine.item_id
            )
            inventory_plan = await self._assets.plan_inventory_changes(
                request.user_id,
                (InventoryAdjustment(medicine.item_id, stack.grade.grade_id, -1),),
            )
            receipt = await self._database.commit(
                TransactionCommand(
                    request.user_id,
                    request.request_id,
                    "道侣突破",
                    inventory_plan.operations + plan.operations,
                    {"道侣编号": plan.companion_id, "丹药编号": medicine.item_id},
                )
            )
            view = await self.inspect(request.user_id)
        except StateConflictError as exc:
            raise CompanionCultivationConflictError(
                "道侣或纳戒已经变化，请重试"
            ) from exc
        except IdempotencyConflictError as exc:
            raise CompanionCultivationConflictError("请求编号已经用于其他操作") from exc
        except (
            AssetStateError,
            CompanionCultivationError,
            CompanionStateError,
            InventoryChangeError,
        ) as exc:
            raise CompanionCultivationFeatureError(str(exc)) from exc
        return CompanionBreakthroughResult(
            view, medicine.name, stack.grade.name, receipt.replayed
        )

    async def forge_law(self, request: CompanionLawRequest) -> CompanionLawResult:
        self._require_initialized()
        law_id = self._resolve_entity("器律", request.law)
        try:
            plan = await self._companion.plan_weapon_law(
                request.user_id, law_id=law_id, slot=request.slot
            )
            reserve_plan = await self._assets.plan_law_reserve_consumption(
                request.user_id, law_id
            )
            receipt = await self._database.commit(
                TransactionCommand(
                    request.user_id,
                    request.request_id,
                    "道侣覆炼",
                    plan.operations + (reserve_plan.operation,),
                    {
                        "道侣编号": plan.companion_id,
                        "器律编号": law_id,
                        "孔位": request.slot,
                    },
                )
            )
            view = await self.inspect(request.user_id)
        except StateConflictError as exc:
            raise CompanionCultivationConflictError(
                "道侣本命武器或器藏已经变化，请重试"
            ) from exc
        except IdempotencyConflictError as exc:
            raise CompanionCultivationConflictError("请求编号已经用于其他操作") from exc
        except (AssetStateError, CompanionCultivationError, CompanionStateError) as exc:
            raise CompanionCultivationFeatureError(str(exc)) from exc
        return CompanionLawResult(view, plan.law_name, plan.slot, receipt.replayed)

    async def _lowest_inventory_stack(self, user_id: str, item_id: str) -> InventoryStack:
        stacks = await self._assets.inventory_stacks(user_id, item_id)
        if not stacks:
            raise CompanionCultivationFeatureError("纳戒中没有该丹药")
        return stacks[0]

    def _resolve_item(self, identifier: str, category: str) -> ItemDetail:
        try:
            item = self._items.inspect(identifier)
        except ItemCatalogError as exc:
            raise CompanionCultivationFeatureError(str(exc)) from exc
        if item.category != category:
            raise CompanionCultivationFeatureError(f"该物品不是{category}")
        return item

    def _resolve_entity(self, section: str, identifier: str) -> str:
        query = str(identifier or "").strip()
        if not query:
            raise CompanionCultivationFeatureError(f"{section}编号或名称不能为空")
        try:
            self._data.entity(section, query)
        except JsonDataError:
            matches = tuple(
                entity_id
                for entity_id, value in self._data.entities(section).items()
                if str(value.get("名称") or "").strip() == query
            )
            if len(matches) != 1:
                raise CompanionCultivationFeatureError(
                    f"未找到唯一{section}：{query}"
                ) from None
            return matches[0]
        return query

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("道侣培养玩法微服务尚未初始化")


__all__ = ["CompanionCultivationFeature"]
