"""解释炼药 JSON，并原子完成药材消耗与成丹产出。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from game.core.asset import (
    AssetEntry,
    AssetService,
    AssetStateError,
    InventoryAdjustment,
    InventoryChangeError,
)
from game.core.data import (
    ContractSet,
    JsonDataError,
    JsonDataService,
    mapping as _mapping,
    nonempty_text,
    nonnegative_int,
    nonnegative_int as _nonnegative_int,
    positive_int,
    positive_int as _positive_int,
)
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    StateConflictError,
    TransactionCommand,
)
from game.core.innate_treasure import (
    InnateTreasureActivation,
    InnateTreasureService,
    activation_payload,
)
from game.core.location import LocationService
from game.core.world import LocationQuery, WorldService
from game.core.world import WORLD_CONTRACT_DATASET, WORLD_CONTRACT_PATH

from .contracts import (
    Alchemist,
    AlchemyAssessment,
    AlchemyConflictError,
    AlchemyError,
    AlchemyMaterial,
    AlchemyMaterialError,
    AlchemyMissingMaterial,
    AlchemyOverview,
    AlchemyPreview,
    AlchemyRecipe,
    AlchemyRecipeEntry,
    AlchemyRecipeList,
    AlchemyResult,
    AlchemyStatus,
    AlchemyUnavailableError,
)
from game.core.data import sequence as _sequence, strict_text, strict_text as _text

_CATEGORIES = ("恢复丹", "战丹", "突破丹", "特殊丹")
#: 编号前缀 → 类别。丹方并进丹药之后，前缀就是**丹药**那四段（10/12/14/16）；
#: 过去的丹方段（11/13/15/17）已经没有实体了。
_RECIPE_CATEGORIES = {"10": "恢复丹", "12": "战丹", "14": "突破丹", "16": "特殊丹"}
_SECONDARY_COST = 1_000_000_000
_GRADE_COST = 100_000


@dataclass(frozen=True)
class _Difficulty:
    level: int
    herb_range: tuple[int, int]
    beast_grade_id: str
    herb_grade_id: str
    secondary_limit: int


@dataclass(frozen=True)
class _HerbIdentity:
    item_id: str
    name: str
    primary_trait: str
    secondary_trait: str


@dataclass(frozen=True)
class _Choice:
    identity: _HerbIdentity
    entry: AssetEntry
    slot: int
    trait: str
    relation: str
    quantity: int


@dataclass
class _Edge:
    target: int
    reverse: int
    capacity: int
    cost: int


class AlchemyService:
    """炼药内容、选材、品级与炼制事务的唯一解释入口。"""

    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService,
        asset: AssetService,
        world: WorldService,
        location: LocationService,
        innate_treasure: InnateTreasureService,
    ) -> None:
        self._data = data
        self._database = database
        self._asset = asset
        self._world = world
        self._location = location
        self._innate_treasure = innate_treasure
        self._initialized = False
        self._recipes: Mapping[str, AlchemyRecipe] = MappingProxyType({})
        self._recipe_by_name: Mapping[str, str] = MappingProxyType({})
        self._recipe_by_medicine: Mapping[str, str] = MappingProxyType({})
        self._methods: Mapping[str, tuple[str, ...]] = MappingProxyType({})
        self._difficulties: Mapping[int, _Difficulty] = MappingProxyType({})
        self._alchemists: Mapping[str, Alchemist] = MappingProxyType({})
        self._herbs: Mapping[str, _HerbIdentity] = MappingProxyType({})
        self._beast_ids: frozenset[str] = frozenset()
        self._town_max_grade_id = ""
        self._page_limit = 0

    def initialize(self) -> AlchemyStatus:
        if self._initialized:
            raise RuntimeError("炼丹核心微服务已经初始化")
        for ready, label in (
            (self._data.status().loaded, "JSON 数据微服务"),
            (self._database.status().initialized, "核心数据库"),
            (self._asset.status().initialized, "玩家资产核心"),
            (self._world.status().initialized, "世界核心"),
            (self._location.status().initialized, "位置核心"),
            (self._innate_treasure.status().initialized, "先天灵宝核心"),
        ):
            if not ready:
                raise RuntimeError(f"{label}必须先于炼丹核心启动")
        rules = self._data.dataset("炼药规则")
        self._methods = MappingProxyType(self._load_methods(rules.get("炉法")))
        self._difficulties = MappingProxyType(
            self._load_difficulties(rules.get("难度"))
        )
        dan_rule = _mapping(rules.get("丹则"), "炼药规则.丹则")
        self._town_max_grade_id = _text(
            _mapping(dan_rule.get("成丹"), "丹则.成丹").get("城镇最高品级"),
            "丹则.成丹.城镇最高品级",
        )
        # 成丹品级按「最低余量进阶」算（算法本身写在下面几处计算里）。声明在数据里，
        # 这里读死，免得数据说一套、实现做另一套。
        grade_rule = _mapping(
            _mapping(dan_rule.get("成丹"), "丹则.成丹").get("品级"), "丹则.成丹.品级"
        )
        if grade_rule.get("算法") != "最低余量进阶":
            raise JsonDataError("成丹品级算法必须是「最低余量进阶」")
        self._herbs = MappingProxyType(self._load_herbs(rules.get("归脉")))
        self._beast_ids = frozenset(_item_ids(self._data, "兽宝"))
        self._recipes = MappingProxyType(self._load_recipes())
        self._recipe_by_name = MappingProxyType(
            {recipe.name: recipe_id for recipe_id, recipe in self._recipes.items()}
        )
        self._recipe_by_medicine = MappingProxyType(
            {
                value: recipe_id
                for recipe_id, recipe in self._recipes.items()
                for value in (recipe.medicine_id, recipe.medicine_name)
            }
        )
        self._alchemists = MappingProxyType(self._load_alchemists())
        paging = _mapping(
            self._data.dataset("炼丹展示").get("分页"), "炼丹展示.分页"
        )
        self._page_limit = _positive_int(paging.get("每页上限"), "炼丹分页.每页上限")
        if tuple(_texts(paging.get("分类顺序"), "炼丹分页.分类顺序")) != _CATEGORIES:
            raise JsonDataError("炼丹分类顺序必须完整且固定")
        self._validate_static_rules(rules)
        self._initialized = True
        return self.status()

    def status(self) -> AlchemyStatus:
        return AlchemyStatus(
            self._initialized,
            len(self._recipes),
            len({recipe.medicine_id for recipe in self._recipes.values()}),
            len(self._methods),
            len(self._alchemists),
            len(self._beast_ids),
            len(self._herbs),
        )

    def recipes(self, category: str) -> tuple[AlchemyRecipe, ...]:
        self._require_initialized()
        normalized = str(category or "").strip()
        if normalized not in _CATEGORIES:
            raise AlchemyError(f"未知丹药分类：{normalized or '<空>'}")
        return tuple(
            sorted(
                (recipe for recipe in self._recipes.values() if recipe.category == normalized),
                key=lambda value: value.recipe_id,
            )
        )

    def assess(
        self, identifier: str, entries: tuple[AssetEntry, ...]
    ) -> AlchemyAssessment:
        self._require_initialized()
        recipe = self._resolve_recipe(identifier)
        difficulty = self._difficulties[recipe.difficulty]
        beast = self._select_beast(entries, difficulty.beast_grade_id)
        herbs, missing, secondary_count = self._match_herbs(
            self._methods[recipe.method], entries, difficulty.herb_grade_id
        )
        missing_values = list(missing)
        if beast is None:
            missing_values.insert(0, AlchemyMissingMaterial("药引", "兽宝", 1))
        if not missing_values and secondary_count > difficulty.secondary_limit:
            missing_values.append(
                AlchemyMissingMaterial(
                    "辅材", "本脉灵植", secondary_count - difficulty.secondary_limit
                )
            )
        grade_id, grade_name = self._medicine_grade(difficulty, beast, herbs)
        return AlchemyAssessment(
            recipe,
            grade_id,
            grade_name,
            beast,
            herbs,
            tuple(missing_values),
            secondary_count,
            difficulty.secondary_limit,
            not missing_values,
        )

    async def overview(self, user_id: str) -> AlchemyOverview:
        normalized = _request_text(user_id, "user_id")
        location_name, alchemist = await self._current_alchemist(normalized)
        return AlchemyOverview(
            normalized,
            location_name,
            alchemist,
            tuple(
                (
                    category,
                    sum(recipe.category == category for recipe in self._recipes.values()),
                )
                for category in _CATEGORIES
            ),
        )

    async def list_recipes(
        self, user_id: str, category: str, page: int = 1
    ) -> AlchemyRecipeList:
        normalized = _request_text(user_id, "user_id")
        normalized_category = str(category or "").strip()
        if normalized_category not in _CATEGORIES:
            raise AlchemyError(f"未知丹药分类：{normalized_category or '<空>'}")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise AlchemyError("页码必须是正整数")
        location_name, alchemist = await self._current_alchemist(normalized)
        entries = await self._material_entries(normalized)
        recipes = tuple(
            sorted(
                (
                    recipe
                    for recipe in self._recipes.values()
                    if recipe.category == normalized_category
                ),
                key=lambda value: value.recipe_id,
            )
        )
        page_count = max(1, (len(recipes) + self._page_limit - 1) // self._page_limit)
        if page > page_count:
            raise AlchemyError(f"页码超出范围：1至{page_count}")
        selected = recipes[(page - 1) * self._page_limit : page * self._page_limit]
        return AlchemyRecipeList(
            normalized,
            location_name,
            alchemist,
            normalized_category,
            tuple(
                AlchemyRecipeEntry(
                    recipe,
                    (
                        preview := self._build_preview(
                            normalized, location_name, alchemist, recipe, entries
                        )
                    ).can_refine,
                    sum(item.quantity for item in preview.missing_materials),
                )
                for recipe in selected
            ),
            page,
            page_count,
        )

    async def preview(self, user_id: str, identifier: str) -> AlchemyPreview:
        normalized = _request_text(user_id, "user_id")
        recipe = self._resolve_recipe(identifier)
        location_name, alchemist = await self._current_alchemist(normalized)
        entries = await self._material_entries(normalized)
        return self._build_preview(
            normalized, location_name, alchemist, recipe, entries
        )

    async def refine(
        self, user_id: str, request_id: str, identifier: str
    ) -> AlchemyResult:
        normalized = _request_text(user_id, "user_id")
        request = _request_text(request_id, "request_id")
        recipe = self._resolve_recipe(identifier)
        committed = await self._database.committed_transaction(normalized, request)
        if committed is not None:
            if (
                committed.receipt.business_type != "炼丹"
                or committed.payload.get("丹药编号") != recipe.recipe_id
            ):
                raise AlchemyConflictError("请求编号已经用于其他操作")
            return self._replayed_result(normalized, recipe, committed.payload)
        preview = await self.preview(normalized, recipe.recipe_id)
        if not preview.can_refine or preview.beast_material is None:
            raise AlchemyMaterialError("纳戒中的兽宝和灵植不足以炼成该丹药")
        materials = (preview.beast_material,) + preview.herb_materials
        adjustments = [
            InventoryAdjustment(item.item_id, item.grade_id, -item.quantity)
            for item in materials
        ]
        activation: InnateTreasureActivation | None = None
        output_quantity = 1
        treasure_effect = await self._innate_treasure.effect(normalized, "炼丹成功")
        if treasure_effect is not None:
            treasure, effect = treasure_effect
            if effect.ability == "返还主要辅材":
                returned = min(
                    preview.herb_materials,
                    key=lambda item: (-item.quantity, item.item_id, item.grade_id),
                )
                returned_quantity = min(
                    returned.quantity, int(effect.values["数量"])
                )
                adjustments.append(
                    InventoryAdjustment(
                        returned.item_id, returned.grade_id, returned_quantity
                    )
                )
                activation = InnateTreasureActivation(
                    treasure.treasure_id,
                    treasure.name,
                    treasure.authority,
                    f"返还{returned.grade_name}{returned.name} × {returned_quantity}",
                )
            elif effect.ability == "增加成丹":
                added = int(effect.values["数量"])
                output_quantity += added
                activation = InnateTreasureActivation(
                    treasure.treasure_id,
                    treasure.name,
                    treasure.authority,
                    f"额外成丹 × {added}",
                )
        adjustments.append(
            InventoryAdjustment(
                preview.recipe.medicine_id,
                preview.medicine_grade_id,
                output_quantity,
            )
        )
        try:
            inventory = await self._asset.plan_inventory_changes(
                normalized, tuple(adjustments)
            )
            output = next(
                change
                for change in inventory.changes
                if change.item_id == preview.recipe.medicine_id
                and change.grade.grade_id == preview.medicine_grade_id
            )
            payload = {
                "地点": preview.location_name,
                "丹师编号": preview.alchemist.alchemist_id,
                "丹药编号": preview.recipe.recipe_id,
                "成丹编号": preview.recipe.medicine_id,
                "成丹品级": preview.medicine_grade_id,
                "原数量": output.before_quantity,
                "现数量": output.after_quantity,
                "药引": _material_payload(preview.beast_material),
                "辅材": [_material_payload(item) for item in preview.herb_materials],
                "先天灵宝": activation_payload(activation),
            }
            receipt = await self._database.commit(
                TransactionCommand(
                    normalized,
                    request,
                    "炼丹",
                    inventory.operations,
                    payload,
                )
            )
        except StateConflictError as exc:
            raise AlchemyConflictError("纳戒已经变化，请重新验药") from exc
        except IdempotencyConflictError as exc:
            raise AlchemyConflictError("请求编号已经用于其他操作") from exc
        except (AssetStateError, InventoryChangeError) as exc:
            raise AlchemyMaterialError(str(exc)) from exc
        return AlchemyResult(
            preview,
            output.before_quantity,
            output.after_quantity,
            receipt.replayed,
            activation,
        )

    def _replayed_result(
        self,
        user_id: str,
        recipe: AlchemyRecipe,
        payload: Mapping[str, object],
    ) -> AlchemyResult:
        try:
            location_name = _payload_text(payload.get("地点"), "炼丹事务.地点")
            alchemist = self._alchemists[location_name]
            if alchemist.alchemist_id != _payload_text(
                payload.get("丹师编号"), "炼丹事务.丹师编号"
            ):
                raise ValueError("炼丹事务丹师与地点不一致")
            beast = _payload_material(
                payload.get("药引"), self._asset, self._data, "药引"
            )
            herbs = _payload_materials(
                payload.get("辅材"), self._asset, self._data, "辅材"
            )
            grade = self._asset.grade(
                _payload_text(payload.get("成丹品级"), "炼丹事务.成丹品级")
            )
            before = _payload_nonnegative_int(payload.get("原数量"), "炼丹事务.原数量")
            after = _payload_positive_int(payload.get("现数量"), "炼丹事务.现数量")
            activation = _payload_activation(payload.get("先天灵宝"))
        except (KeyError, TypeError, ValueError) as exc:
            raise AlchemyConflictError("已提交炼丹事务无法还原") from exc
        difficulty = self._difficulties[recipe.difficulty]
        preview = AlchemyPreview(
            user_id,
            location_name,
            alchemist,
            recipe,
            grade.grade_id,
            grade.name,
            beast,
            herbs,
            (),
            sum(item.relation == "旁脉" for item in herbs),
            difficulty.secondary_limit,
            True,
        )
        return AlchemyResult(preview, before, after, True, activation)

    def _build_preview(
        self,
        user_id: str,
        location_name: str,
        alchemist: Alchemist,
        recipe: AlchemyRecipe,
        entries: tuple[AssetEntry, ...],
    ) -> AlchemyPreview:
        value = self.assess(recipe.recipe_id, entries)
        grade = self._asset.grade(value.medicine_grade_id)
        town_max_grade = self._asset.grade(self._town_max_grade_id)
        if grade.order > town_max_grade.order:
            grade = town_max_grade
        return AlchemyPreview(
            user_id,
            location_name,
            alchemist,
            value.recipe,
            grade.grade_id,
            grade.name,
            value.beast_material,
            value.herb_materials,
            value.missing_materials,
            value.secondary_substitutions,
            value.secondary_substitution_limit,
            value.can_refine,
        )

    def _select_beast(
        self, entries: tuple[AssetEntry, ...], minimum_grade_id: str
    ) -> AlchemyMaterial | None:
        minimum_order = self._asset.grade(minimum_grade_id).order
        candidates = sorted(
            (
                entry
                for entry in entries
                if entry.content_id in self._beast_ids
                and self._asset.grade(entry.grade_id).order >= minimum_order
            ),
            key=lambda entry: (
                self._asset.grade(entry.grade_id).order,
                entry.content_id,
            ),
        )
        if not candidates:
            return None
        entry = candidates[0]
        return AlchemyMaterial(
            entry.content_id,
            entry.name,
            entry.grade_id,
            entry.grade_name,
            "药引",
            "兽宝",
            "药引",
            1,
        )

    def _match_herbs(
        self,
        traits: tuple[str, ...],
        entries: tuple[AssetEntry, ...],
        minimum_grade_id: str,
    ) -> tuple[tuple[AlchemyMaterial, ...], tuple[AlchemyMissingMaterial, ...], int]:
        minimum_order = self._asset.grade(minimum_grade_id).order
        by_item: dict[str, list[AssetEntry]] = {}
        for entry in entries:
            if entry.content_id in self._herbs:
                by_item.setdefault(entry.content_id, []).append(entry)
        choices: list[_Choice] = []
        for item_id in sorted(by_item):
            identity = self._herbs[item_id]
            stacks = sorted(
                (
                    entry
                    for entry in by_item[item_id]
                    if self._asset.grade(entry.grade_id).order >= minimum_order
                ),
                key=lambda entry: self._asset.grade(entry.grade_id).order,
            )
            for slot, trait in enumerate(traits):
                relation = ""
                quantity = 0
                if identity.primary_trait == trait:
                    relation, quantity = "本脉", 1
                elif identity.secondary_trait == trait:
                    relation, quantity = "旁脉", 2
                if relation:
                    entry = next(
                        (value for value in stacks if value.quantity >= quantity), None
                    )
                    if entry is not None:
                        choices.append(
                            _Choice(
                                identity, entry, slot, trait, relation, quantity
                            )
                        )
        matched = _minimum_cost_matching(
            tuple(sorted(by_item)), len(traits), choices, self._asset
        )
        materials = tuple(
            AlchemyMaterial(
                choice.identity.item_id,
                choice.identity.name,
                choice.entry.grade_id,
                choice.entry.grade_name,
                "辅材",
                choice.trait,
                choice.relation,
                choice.quantity,
            )
            for choice in sorted(matched.values(), key=lambda value: value.slot)
        )
        missing_counts: dict[str, int] = {}
        for index, trait in enumerate(traits):
            if index not in matched:
                missing_counts[trait] = missing_counts.get(trait, 0) + 1
        missing = tuple(
            AlchemyMissingMaterial("辅材", trait, quantity)
            for trait, quantity in missing_counts.items()
        )
        return materials, missing, sum(item.relation == "旁脉" for item in materials)

    def _medicine_grade(
        self,
        difficulty: _Difficulty,
        beast: AlchemyMaterial | None,
        herbs: tuple[AlchemyMaterial, ...],
    ) -> tuple[str, str]:
        beast_minimum = self._asset.grade(difficulty.beast_grade_id)
        herb_minimum = self._asset.grade(difficulty.herb_grade_id)
        base_order = max(beast_minimum.order, herb_minimum.order)
        surplus = [
            self._asset.grade(beast.grade_id).order - beast_minimum.order
        ] if beast is not None else [0]
        surplus.extend(
            self._asset.grade(herb.grade_id).order - herb_minimum.order
            for herb in herbs
        )
        target_order = min(5, base_order + max(0, min(surplus)))
        grade = next(
            self._asset.grade(grade_id)
            for grade_id in ("01", "02", "03", "04", "05")
            if self._asset.grade(grade_id).order == target_order
        )
        return grade.grade_id, grade.name

    async def _material_entries(self, user_id: str) -> tuple[AssetEntry, ...]:
        snapshot = await self._asset.snapshot(user_id)
        return tuple(
            entry
            for entry in snapshot.entries
            if entry.category == "基础物品" and entry.subcategory in {"兽宝", "灵植"}
        )

    async def _current_alchemist(self, user_id: str) -> tuple[str, Alchemist]:
        self._require_initialized()
        current = await self._location.current(user_id)
        place = self._world.locate(LocationQuery(xy=current.xy))
        if not place.location_name or "炼丹" not in place.available_functions:
            raise AlchemyUnavailableError("此地没有能够主持炼丹的丹师")
        alchemist = self._alchemists.get(place.location_name)
        if alchemist is None:
            raise AlchemyUnavailableError("此地没有能够主持炼丹的丹师")
        return place.location_name, alchemist

    def _resolve_recipe(self, identifier: str) -> AlchemyRecipe:
        self._require_initialized()
        query = str(identifier or "").strip()
        recipe = self._recipes.get(query)
        if recipe is None:
            recipe = self._recipes.get(self._recipe_by_name.get(query, ""))
        if recipe is None:
            recipe = self._recipes.get(self._recipe_by_medicine.get(query, ""))
        if recipe is None:
            raise AlchemyError(f"未找到唯一丹药：{query or '<空>'}")
        return recipe

    def _load_methods(self, value: object) -> dict[str, tuple[str, ...]]:
        result: dict[str, tuple[str, ...]] = {}
        for raw in _sequence(value, "炼药规则.炉法"):
            row = _mapping(raw, "炉法[]")
            name = _text(row.get("名称"), "炉法.名称")
            if name in result:
                raise JsonDataError(f"炉法名称重复：{name}")
            traits: list[str] = []
            for material in _sequence(row.get("辅材"), f"炉法 {name}.辅材"):
                material_row = _mapping(material, f"炉法 {name}.辅材[]")
                trait = _text(material_row.get("药脉"), f"炉法 {name}.药脉")
                traits.extend(
                    [trait]
                    * _positive_int(material_row.get("味数"), f"炉法 {name}.味数")
                )
            result[name] = tuple(traits)
        return result

    def _load_difficulties(self, value: object) -> dict[int, _Difficulty]:
        result: dict[int, _Difficulty] = {}
        for raw in _sequence(value, "炼药规则.难度"):
            row = _mapping(raw, "难度[]")
            level = _positive_int(row.get("炼制难度"), "难度.炼制难度")
            if level in result:
                raise JsonDataError(f"炼制难度重复：{level}")
            limits = _mapping(row.get("辅材总味数"), f"难度 {level}.辅材总味数")
            result[level] = _Difficulty(
                level,
                (
                    _positive_int(limits.get("最少"), f"难度 {level}.最少"),
                    _positive_int(limits.get("最多"), f"难度 {level}.最多"),
                ),
                _text(row.get("最低药引品级"), f"难度 {level}.最低药引品级"),
                _text(row.get("最低辅材品级"), f"难度 {level}.最低辅材品级"),
                _nonnegative_int(row.get("旁脉替代上限"), f"难度 {level}.旁脉替代上限"),
            )
        return result

    def _load_herbs(self, value: object) -> dict[str, _HerbIdentity]:
        result: dict[str, _HerbIdentity] = {}
        for raw in _sequence(value, "炼药规则.归脉"):
            row = _mapping(raw, "归脉[]")
            pool = _text(row.get("灵植池"), "归脉.灵植池")
            primary = _text(row.get("本脉"), "归脉.本脉")
            secondary = _text(row.get("旁脉"), "归脉.旁脉")
            for item_id in self._data.pool_members((pool,), "基础物品"):
                if item_id in result:
                    raise JsonDataError(f"灵植重复归脉：{item_id}")
                result[item_id] = _HerbIdentity(
                    item_id, _entity_name(self._data, item_id), primary, secondary
                )
        return result

    def _load_recipes(self) -> dict[str, AlchemyRecipe]:
        """丹药**自己就是处方**：`炉法` / `炼制难度` 与 `使用效果` 写在同一份实体里。

        丹方并进丹药之后，`recipe_id` 与 `medicine_id` 是同一个编号（第 76 轮）；
        过去那张「丹方 → 成丹」的跳转表不再存在。
        """

        result: dict[str, AlchemyRecipe] = {}
        names: set[str] = set()
        contract = ContractSet.from_dataset(
            self._data.dataset("炼丹字段契约"), "物品/炼丹/规则/炼丹字段契约.json"
        )
        for medicine_id, raw in self._data.entities("丹药").items():
            contract.validate(raw, "丹药", f"丹药 {medicine_id}")
            name = _text(raw.get("名称"), f"丹药 {medicine_id}.名称")
            method = _text(raw.get("炉法"), f"丹药 {name}.炉法")
            difficulty = _positive_int(raw.get("炼制难度"), f"丹药 {name}.炼制难度")
            if name in names:
                raise JsonDataError(f"丹药名称重复：{name}")
            if method not in self._methods or difficulty not in self._difficulties:
                raise JsonDataError(f"丹药引用未知炉法或难度：{name}")
            category = _RECIPE_CATEGORIES.get(medicine_id[:2], "")
            if category not in _CATEGORIES:
                raise JsonDataError(f"丹药类别错误：{name} -> {category}")
            names.add(name)
            result[medicine_id] = AlchemyRecipe(
                medicine_id,
                name,
                category,
                difficulty,
                method,
                medicine_id,
                name,
            )
        return result

    def _load_alchemists(self) -> dict[str, Alchemist]:
        result: dict[str, Alchemist] = {}
        contract = ContractSet.from_dataset(
            self._data.dataset(WORLD_CONTRACT_DATASET), WORLD_CONTRACT_PATH
        )
        for alchemist_id, raw in self._data.entities("炼丹师").items():
            contract.validate(raw, "炼丹师", f"炼丹师 {alchemist_id}")
            location = self._data.entity_record("炼丹师", alchemist_id).directory_owner
            if not location:
                raise JsonDataError(f"炼丹师 {alchemist_id} 缺少地点目录归属")
            if location in result:
                raise JsonDataError(f"同一地点不能有多名掌炉丹师：{location}")
            result[location] = Alchemist(
                alchemist_id,
                _text(raw.get("名称"), f"炼丹师 {alchemist_id}.名称"),
                location,
                _text(raw.get("称号"), f"炼丹师 {alchemist_id}.称号"),
                _text(raw.get("炉名"), f"炼丹师 {alchemist_id}.炉名"),
                _text(raw.get("丹道传承"), f"炼丹师 {alchemist_id}.丹道传承"),
                _text(raw.get("话语风格"), f"炼丹师 {alchemist_id}.话语风格"),
                _speech(raw.get("话语"), f"炼丹师 {alchemist_id}.话语"),
            )
        return result

    def _validate_static_rules(self, rules: Mapping[str, object]) -> None:
        for recipe in self._recipes.values():
            difficulty = self._difficulties[recipe.difficulty]
            count = len(self._methods[recipe.method])
            if not difficulty.herb_range[0] <= count <= difficulty.herb_range[1]:
                raise JsonDataError(f"丹药炉法味数与难度不一致：{recipe.name}")
        locations = {
            item.name
            for item in self._world.map_view().locations
            if "炼丹" in item.available_functions
        }
        if set(self._alchemists) != locations:
            raise JsonDataError(
                f"炼丹地点与丹师不一一对应：缺少{sorted(locations - set(self._alchemists))}，"
                f"多余{sorted(set(self._alchemists) - locations)}"
            )
        if set(self._herbs) != _item_ids(self._data, "灵植"):
            raise JsonDataError("归脉没有完整且唯一覆盖全部灵植")
        dan_rule = _mapping(rules.get("丹则"), "炼药规则.丹则")
        if _mapping(dan_rule.get("药引"), "丹则.药引") != {
            "类别": "兽宝",
            "每炉数量": 1,
        }:
            raise JsonDataError("炼丹核心只支持每炉一件兽宝作为药引")
        output = _mapping(dan_rule.get("成丹"), "丹则.成丹")
        if output.get("基础数量") != 1:
            raise JsonDataError("炼丹核心只支持每炉基础产出一枚丹药")
        if output.get("城镇最高品级") != "04":
            raise JsonDataError("城镇炼丹最高品级必须为天品")

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("炼丹核心微服务尚未初始化")


# 本函数与 `game/core/forging/service.py` 的同名函数**逐字相同**（差异只有换行格式）。
# 两处必须同步修改：只改一处，炼器与炼丹的「最省匹配」就会悄悄分叉。
def _minimum_cost_matching(
    item_ids: tuple[str, ...],
    slot_count: int,
    choices: Sequence[_Choice],
    asset: AssetService,
) -> dict[int, _Choice]:
    if not item_ids or not slot_count:
        return {}
    item_index = {item_id: index for index, item_id in enumerate(item_ids)}
    source = 0
    item_start = 1
    slot_start = item_start + len(item_ids)
    sink = slot_start + slot_count
    graph: list[list[_Edge]] = [[] for _ in range(sink + 1)]

    def add_edge(origin: int, target: int, capacity: int, cost: int) -> _Edge:
        forward = _Edge(target, len(graph[target]), capacity, cost)
        backward = _Edge(origin, len(graph[origin]), 0, -cost)
        graph[origin].append(forward)
        graph[target].append(backward)
        return forward

    for index in range(len(item_ids)):
        add_edge(source, item_start + index, 1, 0)
    for slot in range(slot_count):
        add_edge(slot_start + slot, sink, 1, 0)
    tracked: list[tuple[_Choice, _Edge]] = []
    for choice in sorted(
        choices,
        key=lambda value: (
            value.identity.item_id,
            value.slot,
            value.relation,
            value.entry.grade_id,
        ),
    ):
        grade_order = asset.grade(choice.entry.grade_id).order
        rank = item_index[choice.identity.item_id]
        cost = (
            (_SECONDARY_COST if choice.relation == "旁脉" else 0)
            + grade_order * _GRADE_COST
            + rank
        )
        tracked.append(
            (
                choice,
                add_edge(
                    item_start + item_index[choice.identity.item_id],
                    slot_start + choice.slot,
                    1,
                    cost,
                ),
            )
        )
    while True:
        distances = [10**30] * len(graph)
        previous: list[tuple[int, int] | None] = [None] * len(graph)
        distances[source] = 0
        for _ in range(len(graph) - 1):
            changed = False
            for origin, edges in enumerate(graph):
                if distances[origin] == 10**30:
                    continue
                for edge_index, edge in enumerate(edges):
                    if edge.capacity and distances[origin] + edge.cost < distances[edge.target]:
                        distances[edge.target] = distances[origin] + edge.cost
                        previous[edge.target] = (origin, edge_index)
                        changed = True
            if not changed:
                break
        if previous[sink] is None:
            break
        node = sink
        while node != source:
            origin, edge_index = previous[node]  # type: ignore[misc]
            edge = graph[origin][edge_index]
            edge.capacity -= 1
            graph[node][edge.reverse].capacity += 1
            node = origin
    return {choice.slot: choice for choice, edge in tracked if edge.capacity == 0}


def _material_payload(material: AlchemyMaterial) -> dict[str, object]:
    return {
        "编号": material.item_id,
        "品级": material.grade_id,
        "数量": material.quantity,
        "用途": material.role,
        "药脉": material.trait,
        "关系": material.relation,
    }


def _payload_activation(value: object) -> InnateTreasureActivation | None:
    if value is None:
        return None
    raw = _mapping(value, "炼丹事务.先天灵宝")
    return InnateTreasureActivation(
        _payload_text(raw.get("编号"), "炼丹事务.先天灵宝.编号"),
        _payload_text(raw.get("名称"), "炼丹事务.先天灵宝.名称"),
        _payload_text(raw.get("权柄"), "炼丹事务.先天灵宝.权柄"),
        _payload_text(raw.get("结果"), "炼丹事务.先天灵宝.结果"),
    )


def _payload_materials(
    value: object,
    asset: AssetService,
    data: JsonDataService,
    label: str,
) -> tuple[AlchemyMaterial, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"炼丹事务.{label}必须是数组")
    return tuple(_payload_material(raw, asset, data, label) for raw in value)


def _payload_material(
    value: object,
    asset: AssetService,
    data: JsonDataService,
    label: str,
) -> AlchemyMaterial:
    raw = _mapping(value, f"炼丹事务.{label}")
    item_id = _payload_text(raw.get("编号"), f"炼丹事务.{label}.编号")
    grade = asset.grade(_payload_text(raw.get("品级"), f"炼丹事务.{label}.品级"))
    return AlchemyMaterial(
        item_id,
        _entity_name(data, item_id),
        grade.grade_id,
        grade.name,
        _payload_text(raw.get("用途"), f"炼丹事务.{label}.用途"),
        _payload_text(raw.get("药脉"), f"炼丹事务.{label}.药脉"),
        _payload_text(raw.get("关系"), f"炼丹事务.{label}.关系"),
        _payload_positive_int(raw.get("数量"), f"炼丹事务.{label}.数量"),
    )


def _item_ids(data: JsonDataService, category: str) -> set[str]:
    return {
        item_id
        for item_id in data.entities("基础物品")
        if data.entity_record("基础物品", item_id).number_category == category
    }


def _entity_name(data: JsonDataService, item_id: str) -> str:
    return _text(data.entity("基础物品", item_id).get("名称"), f"物品 {item_id}.名称")


def _texts(value: object, label: str) -> tuple[str, ...]:
    return tuple(_text(raw, label) for raw in _sequence(value, label))


def _speech(value: object, label: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    expected = {"总览", "审材", "齐备", "不足", "完成"}
    if set(value) != expected:
        raise JsonDataError(f"{label}必须完整包含：{'、'.join(sorted(expected))}")
    return MappingProxyType({key: _text(value[key], f"{label}.{key}") for key in expected})


def _request_text(value: object, label: str) -> str:
    return nonempty_text(value, label, error=AlchemyError)


def _payload_text(value: object, label: str) -> str:
    return strict_text(value, label, error=ValueError)


def _payload_positive_int(value: object, label: str) -> int:
    return positive_int(value, label, error=ValueError)


def _payload_nonnegative_int(value: object, label: str) -> int:
    return nonnegative_int(value, label, error=ValueError)


__all__ = ["AlchemyService"]
