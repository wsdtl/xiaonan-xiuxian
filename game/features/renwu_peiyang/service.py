"""人物培养的事务编排。"""

from __future__ import annotations

from collections.abc import Mapping

from game.core.asset import (
    AssetService,
    AssetStateError,
    InventoryAdjustment,
    InventoryChangeError,
)
from game.core.character import (
    CharacterCultivationError,
    CharacterService,
    CharacterStateError,
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
from game.core.innate_treasure import (
    InnateTreasureActivation,
    InnateTreasureService,
)
from game.core.item_catalog import ItemCatalogError, ItemCatalogService
from game.features.presentation import require_mapping

from .contracts import (
    CharacterBreakthroughRequest,
    CharacterBreakthroughResult,
    CharacterCultivationConflictError,
    CharacterCultivationFeatureError,
    CharacterCultivationView,
    CharacterEquipRequest,
    CharacterEquipResult,
    CharacterLawRequest,
    CharacterLawResult,
)


class CharacterCultivationFeature:
    """组合核心服务完成人物培养，不拥有角色状态。"""

    def __init__(
        self,
        data: JsonDataService,
        character: CharacterService,
        assets: AssetService,
        items: ItemCatalogService,
        growth: GrowthService,
        forging: ForgingService,
        database: DatabaseService,
        innate_treasure: InnateTreasureService,
    ) -> None:
        self._data = data
        self._character = character
        self._assets = assets
        self._items = items
        self._growth = growth
        self._forging = forging
        self._database = database
        self._innate_treasure = innate_treasure
        self._initialized = False
        self._copy: Mapping[str, object] = {}

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("人物培养玩法微服务已经初始化")
        for ready, label in (
            (self._character.status().initialized, "角色核心"),
            (self._assets.status().initialized, "资产核心"),
            (self._items.status().initialized, "物品核心"),
            (self._growth.status().initialized, "成长核心"),
            (self._forging.status().initialized, "炼器核心"),
            (self._database.status().initialized, "数据库核心"),
            (self._innate_treasure.status().initialized, "先天灵宝核心"),
        ):
            if not ready:
                raise RuntimeError(f"{label}必须先于人物培养玩法启动")
        dataset = self._data.dataset("培养展示")
        self._copy = require_mapping(dataset.get("文本"), "玩法/培养/展示/文本.json")
        require_mapping(self._copy.get("人物"), "培养文本.人物")
        require_mapping(self._copy.get("装配"), "培养文本.装配")
        require_mapping(self._copy.get("突破"), "培养文本.突破")
        require_mapping(self._copy.get("覆炼"), "培养文本.覆炼")
        self._initialized = True

    def copy(self, section: str, key: str) -> str:
        self._require_initialized()
        value = require_mapping(self._copy.get(section), f"培养文本.{section}").get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"培养展示缺少文本：{section}.{key}")
        return value.strip()

    async def inspect(self, user_id: str) -> CharacterCultivationView:
        self._require_initialized()
        try:
            profile = await self._character.profile(user_id)
            return CharacterCultivationView(
                profile,
                self._growth.experience_required(profile.level),
                self._forging.weapon_experience_required(profile.weapon.level),
            )
        except (CharacterStateError, ValueError) as exc:
            raise CharacterCultivationFeatureError(str(exc)) from exc

    async def equip(self, request: CharacterEquipRequest) -> CharacterEquipResult:
        self._require_initialized()
        content_id = self._resolve_entity(request.category, request.content)
        try:
            plan = await self._character.plan_equip(
                request.user_id,
                category=request.category,
                content_id=content_id,
                grade_id=request.grade,
                slot=request.slot,
            )
            operations = list(
                ((plan.reserve_operation,) if plan.reserve_operation else ())
                + (plan.operation,)
            )
            activation: InnateTreasureActivation | None = None
            if plan.category in {"真意", "气机"} and plan.replaced_content_id:
                treasure_effect = await self._innate_treasure.effect(
                    request.user_id, "真意气机替换"
                )
                if treasure_effect is not None:
                    treasure, effect = treasure_effect
                    if effect.ability == "保留被替换资粮":
                        returned = await self._assets.plan_cultivation_reserve_change(
                            request.user_id,
                            category=plan.category,
                            content_id=plan.replaced_content_id,
                            grade_id=plan.replaced_grade_id,
                            quantity_delta=1,
                        )
                        operations.append(returned.operation)
                        activation = InnateTreasureActivation(
                            treasure.treasure_id,
                            treasure.name,
                            treasure.authority,
                            f"返还被替换的{returned.stack.grade.name}{returned.stack.name} × 1",
                        )
            receipt = await self._database.commit(
                TransactionCommand(
                    request.user_id,
                    request.request_id,
                    "人物装配",
                    tuple(operations),
                    {
                        "类别": plan.category,
                        "编号": plan.content_id,
                        "品级": plan.grade_id,
                        "槽位": plan.slot,
                    },
                )
            )
            profile = await self._character.profile(request.user_id)
        except StateConflictError as exc:
            raise CharacterCultivationConflictError(
                "人物修行槽或修行资粮已经变化，请重试"
            ) from exc
        except IdempotencyConflictError as exc:
            raise CharacterCultivationConflictError("请求编号已经用于其他操作") from exc
        except (AssetStateError, CharacterCultivationError, CharacterStateError) as exc:
            raise CharacterCultivationFeatureError(str(exc)) from exc
        return CharacterEquipResult(
            profile, plan.category, plan.slot, plan.content_name, receipt.replayed
            , activation
        )

    async def breakthrough(
        self, request: CharacterBreakthroughRequest
    ) -> CharacterBreakthroughResult:
        self._require_initialized()
        medicine = self._resolve_item(request.medicine, "丹药")
        try:
            stack = await self._lowest_inventory_stack(
                request.user_id, medicine.item_id
            )
            activation: InnateTreasureActivation | None = None
            permanent_ratio = 0.0
            treasure_effect = await self._innate_treasure.effect(
                request.user_id, "人物突破"
            )
            if treasure_effect is not None:
                treasure, effect = treasure_effect
                if effect.ability == "提高永久属性":
                    permanent_ratio = float(effect.values["比例"])
            character_plan = await self._character.plan_breakthrough(
                request.user_id,
                medicine_id=medicine.item_id,
                permanent_attribute_ratio=permanent_ratio,
            )
            if permanent_ratio and character_plan.permanent_attributes:
                activation = InnateTreasureActivation(
                    treasure.treasure_id,
                    treasure.name,
                    treasure.authority,
                    "突破永久属性提高，且每项最低增加1点",
                )
            inventory_plan = await self._assets.plan_inventory_changes(
                request.user_id,
                (InventoryAdjustment(medicine.item_id, stack.grade.grade_id, -1),),
            )
            receipt = await self._database.commit(
                TransactionCommand(
                    request.user_id,
                    request.request_id,
                    "人物突破",
                    inventory_plan.operations + (character_plan.operation,),
                    {"丹药编号": medicine.item_id},
                )
            )
            profile = await self._character.profile(request.user_id)
        except StateConflictError as exc:
            raise CharacterCultivationConflictError(
                "人物或纳戒已经变化，请重试"
            ) from exc
        except IdempotencyConflictError as exc:
            raise CharacterCultivationConflictError("请求编号已经用于其他操作") from exc
        except (
            AssetStateError,
            CharacterCultivationError,
            CharacterStateError,
            InventoryChangeError,
        ) as exc:
            raise CharacterCultivationFeatureError(str(exc)) from exc
        return CharacterBreakthroughResult(
            profile, medicine.name, character_plan.realm_name_after, receipt.replayed
            , activation
        )

    async def forge_law(self, request: CharacterLawRequest) -> CharacterLawResult:
        self._require_initialized()
        law_id = self._resolve_entity("器律", request.law)
        try:
            character_plan = await self._character.plan_weapon_law(
                request.user_id, law_id=law_id, slot=request.slot
            )
            reserve_plan = await self._assets.plan_law_reserve_consumption(
                request.user_id, law_id
            )
            receipt = await self._database.commit(
                TransactionCommand(
                    request.user_id,
                    request.request_id,
                    "人物覆炼",
                    (reserve_plan.operation, character_plan.operation),
                    {"器律编号": law_id, "孔位": request.slot},
                )
            )
            profile = await self._character.profile(request.user_id)
        except StateConflictError as exc:
            raise CharacterCultivationConflictError(
                "本命武器或器藏已经变化，请重试"
            ) from exc
        except IdempotencyConflictError as exc:
            raise CharacterCultivationConflictError("请求编号已经用于其他操作") from exc
        except (AssetStateError, CharacterCultivationError, CharacterStateError) as exc:
            raise CharacterCultivationFeatureError(str(exc)) from exc
        return CharacterLawResult(
            profile, character_plan.law_name, character_plan.slot, receipt.replayed
        )

    async def _lowest_inventory_stack(self, user_id: str, item_id: str):
        stacks = await self._assets.inventory_stacks(user_id, item_id)
        if not stacks:
            raise CharacterCultivationFeatureError("纳戒中没有该丹药")
        return stacks[0]

    def _resolve_item(self, identifier: str, category: str):
        try:
            item = self._items.inspect(identifier)
        except ItemCatalogError as exc:
            raise CharacterCultivationFeatureError(str(exc)) from exc
        if item.category != category:
            raise CharacterCultivationFeatureError(f"该物品不是{category}")
        return item

    def _resolve_entity(self, section: str, identifier: str) -> str:
        query = str(identifier or "").strip()
        if not query:
            raise CharacterCultivationFeatureError(f"{section}编号或名称不能为空")
        try:
            self._data.entity(section, query)
        except JsonDataError:
            matches = tuple(
                entity_id
                for entity_id, value in self._data.entities(section).items()
                if str(value.get("名称") or "").strip() == query
            )
            if len(matches) != 1:
                raise CharacterCultivationFeatureError(
                    f"未找到唯一{section}：{query}"
                ) from None
            return matches[0]
        return query

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("人物培养玩法微服务尚未初始化")


__all__ = ["CharacterCultivationFeature"]
