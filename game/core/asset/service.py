"""从数据库状态和正式 JSON 生成玩家资产只读视图。"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from game.core.data import JsonDataError, JsonDataService, mapping, nonempty_text, positive_int
from game.core.database import (
    DatabaseService,
    StateAddress,
    StateMutation,
    StateSnapshot,
)

from .contracts import (
    AssetCategory,
    AssetEntry,
    AssetGrade,
    AssetSnapshot,
    AssetSortRules,
    AssetStateError,
    AssetStatus,
    AssetSubcategory,
    CultivationAcquisition,
    CultivationAcquisitionPlan,
    CultivationAcquisitionResult,
    CultivationOwnership,
    CultivationReserveChangePlan,
    CultivationReserveStack,
    FormationReserveAcquisitionPlan,
    FormationReserveConsumptionPlan,
    FormationReserveStack,
    InventoryAdjustment,
    InventoryChange,
    InventoryChangeError,
    InventoryMutationPlan,
    InventoryStack,
    LawReserveAcquisitionPlan,
    LawReserveChangePlan,
    LawReserveStack,
)

_STATE_TYPES = frozenset(
    {
        "inventory",
        "cultivation_library",
        "cultivation_reserve",
        "law_reserve",
        "formation_reserve",
        "knowledge",
    }
)
_CULTIVATION_RESERVE_CATEGORIES = frozenset({"真意", "气机"})


class AssetService:
    """解释玩家资产，并为跨领域事务生成普通物品变更计划。"""

    state_types = _STATE_TYPES

    def __init__(self, data: JsonDataService, database: DatabaseService) -> None:
        self._data = data
        self._database = database
        self._initialized = False
        self._categories: tuple[AssetCategory, ...] = ()
        self._category_by_state: dict[str, str] = {}
        self._subcategory_rules: dict[tuple[str, str], Mapping[str, object]] = {}
        self._prefixes: dict[str, tuple[str, str]] = {}
        self._grades: dict[str, AssetGrade] = {}
        self._grade_drop_weights: dict[str, float] = {}
        self._grade_names: dict[str, str] = {}
        self._page_limit = 0
        self._sort_rules = AssetSortRules(False, False, False, False)

    def initialize(self) -> AssetStatus:
        if self._initialized:
            raise RuntimeError("玩家资产核心微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据微服务必须先于玩家资产服务启动")
        if not self._database.status().initialized:
            raise RuntimeError("核心数据库必须先于玩家资产服务启动")

        layout = _mapping(
            self._data.dataset("纳戒展示").get("分类"),
            "物品/基础物品/展示/分类.json",
        )
        self._page_limit = _positive_int(layout.get("每页上限"), "纳戒.每页上限")
        if self._page_limit > 50:
            raise JsonDataError("纳戒每页上限不能超过 50")
        self._load_prefixes()
        self._load_grades()
        self._validate_cultivation_rules()
        self._load_categories(layout.get("大类"))
        self._sort_rules = _sort_rules(layout.get("排序"))
        self._initialized = True
        return self.status()

    def status(self) -> AssetStatus:
        return AssetStatus(
            initialized=self._initialized,
            category_count=len(self._categories),
            subcategory_count=sum(
                len(category.subcategories) for category in self._categories
            ),
            page_limit=self._page_limit,
        )

    async def snapshot(self, user_id: str) -> AssetSnapshot:
        self._require_initialized()
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise ValueError("user_id 不能为空")
        snapshots = await self._database.list_for_user(normalized_user_id)
        equipped = _equipped_content(snapshots)
        entries = tuple(
            self._entry(snapshot, equipped)
            for snapshot in snapshots
            if snapshot.address.state_type in _STATE_TYPES
        )
        return AssetSnapshot(
            user_id=normalized_user_id,
            categories=self._categories,
            entries=entries,
            page_limit=self._page_limit,
            sort_rules=self._sort_rules,
        )

    def grade(self, grade_id: str) -> AssetGrade:
        self._require_initialized()
        normalized = str(grade_id or "").strip()
        grade = self._grades.get(normalized)
        if grade is None:
            resolved_id = self._grade_names.get(_normalize(normalized))
            grade = self._grades.get(resolved_id or "")
        if grade is None:
            raise InventoryChangeError(f"未知物品品级：{normalized or '<空>'}")
        return grade

    def draw_drop_grade(self, *, seed: int) -> AssetGrade:
        """按物品规则的逆权重抽取一次掉落品级。"""

        self._require_initialized()
        source = random.Random(seed)
        grade_ids = tuple(sorted(self._grades, key=lambda key: self._grades[key].order))
        weights = tuple(self._grade_drop_weights[grade_id] for grade_id in grade_ids)
        return self._grades[source.choices(grade_ids, weights=weights, k=1)[0]]

    async def inventory_stacks(
        self, user_id: str, item_id: str
    ) -> tuple[InventoryStack, ...]:
        self._require_initialized()
        normalized_user_id = _required_text(user_id, "user_id")
        normalized_item_id = _required_text(item_id, "物品编号")
        item_name = _inventory_name(self._data, normalized_item_id)
        addresses = tuple(
            StateAddress(
                normalized_user_id,
                "inventory",
                f"{normalized_item_id}:{grade_id}",
            )
            for grade_id in self._grades
        )
        snapshots = await self._database.get_many(addresses)
        result: list[InventoryStack] = []
        for snapshot in snapshots:
            value = _mapping(snapshot.value, "普通物品")
            grade_id, _ = snapshot.address.state_key.rsplit(":", 1)
            if grade_id != normalized_item_id:
                raise AssetStateError("普通物品状态键与查询编号不一致")
            grade = self.grade(_text(value.get("品级"), "普通物品.品级"))
            _expect_key(snapshot, f"{normalized_item_id}:{grade.grade_id}")
            result.append(
                InventoryStack(
                    normalized_item_id,
                    item_name,
                    grade,
                    _positive_int(value.get("数量"), "普通物品.数量"),
                    snapshot.version,
                )
            )
        return tuple(sorted(result, key=lambda stack: stack.grade.order))

    def initial_inventory_mutations(
        self,
        user_id: str,
        items: Sequence[tuple[str, str, str, int]],
    ) -> tuple[StateMutation, ...]:
        """为创建人物事务生成由资产核心负责的初始背包状态。"""

        self._require_initialized()
        normalized_user_id = _required_text(user_id, "user_id")
        result: list[StateMutation] = []
        seen: set[tuple[str, str]] = set()
        for dataset, item_id, grade_id, quantity in items:
            normalized_dataset = _required_text(dataset, "初始物品.数据集")
            normalized_item_id = _required_text(item_id, "初始物品.编号")
            normalized_grade_id = self.grade(grade_id).grade_id
            if (
                isinstance(quantity, bool)
                or not isinstance(quantity, int)
                or quantity < 1
            ):
                raise InventoryChangeError("初始物品数量必须是正整数")
            _entity_name(self._data, normalized_dataset, normalized_item_id)
            key = (normalized_item_id, normalized_grade_id)
            if key in seen:
                raise InventoryChangeError(
                    f"初始物品重复：{normalized_item_id}:{normalized_grade_id}"
                )
            seen.add(key)
            result.append(
                StateMutation(
                    normalized_user_id,
                    "inventory",
                    f"{normalized_item_id}:{normalized_grade_id}",
                    {
                        "编号": normalized_item_id,
                        "品级": normalized_grade_id,
                        "数量": quantity,
                    },
                    0,
                )
            )
        return tuple(result)

    async def plan_inventory_changes(
        self,
        user_id: str,
        adjustments: Sequence[InventoryAdjustment],
    ) -> InventoryMutationPlan:
        """合并同一库存地址的变化，生成可与其他领域一起提交的操作。"""

        self._require_initialized()
        normalized_user_id = _required_text(user_id, "user_id")
        totals: dict[tuple[str, str], int] = {}
        for adjustment in adjustments:
            item_id = _required_text(adjustment.item_id, "库存变化.物品编号")
            grade_id = self.grade(adjustment.grade_id).grade_id
            delta = adjustment.quantity_delta
            if isinstance(delta, bool) or not isinstance(delta, int) or delta == 0:
                raise InventoryChangeError("库存变化数量必须是非零整数")
            _inventory_name(self._data, item_id)
            key = (item_id, grade_id)
            totals[key] = totals.get(key, 0) + delta
        totals = {key: delta for key, delta in totals.items() if delta}
        if not totals:
            return InventoryMutationPlan((), ())

        addresses = tuple(
            StateAddress(normalized_user_id, "inventory", f"{item_id}:{grade_id}")
            for item_id, grade_id in totals
        )
        snapshots = await self._database.get_many(addresses)
        snapshot_by_key = {
            snapshot.address.state_key: snapshot for snapshot in snapshots
        }
        changes: list[InventoryChange] = []
        operations: list[StateMutation] = []
        for item_id, grade_id in sorted(
            totals,
            key=lambda key: (key[0], self._grades[key[1]].order),
        ):
            state_key = f"{item_id}:{grade_id}"
            snapshot = snapshot_by_key.get(state_key)
            before = 0
            version = 0
            if snapshot is not None:
                value = _mapping(snapshot.value, f"inventory/{state_key}")
                before = _positive_int(value.get("数量"), f"inventory/{state_key}.数量")
                version = snapshot.version
            after = before + totals[(item_id, grade_id)]
            if after < 0:
                item_name = _inventory_name(self._data, item_id)
                grade_name = self._grades[grade_id].name
                raise InventoryChangeError(
                    f"{grade_name}{item_name}数量不足：现有{before}，需要{-totals[(item_id, grade_id)]}"
                )
            value = (
                {"编号": item_id, "品级": grade_id, "数量": after} if after else None
            )
            operations.append(
                StateMutation(
                    normalized_user_id,
                    "inventory",
                    state_key,
                    value,
                    version,
                )
            )
            changes.append(
                InventoryChange(
                    item_id,
                    _inventory_name(self._data, item_id),
                    self._grades[grade_id],
                    before,
                    after,
                )
            )
        return InventoryMutationPlan(tuple(changes), tuple(operations))

    async def cultivation_ownership(
        self,
        user_id: str,
        category: str,
        content_id: str,
        grade_id: str,
    ) -> CultivationOwnership:
        """精确确认玩家道藏中的一个修行实例。"""

        self._require_initialized()
        normalized_user_id = _required_text(user_id, "user_id")
        normalized_category = _required_text(category, "修行类别")
        if normalized_category != "功法":
            raise AssetStateError(f"不能装配该类别：{normalized_category}")
        normalized_content_id = _required_text(content_id, "修行编号")
        normalized_grade_id = self.grade(grade_id).grade_id
        record = self._data.entity_record(normalized_category, normalized_content_id)
        if record.number_category != normalized_category:
            raise AssetStateError("修行编号类别不匹配")
        snapshot = await self._database.get(
            StateAddress(
                normalized_user_id,
                "cultivation_library",
                normalized_content_id,
            )
        )
        if snapshot is None:
            raise AssetStateError("道藏中没有该修行内容")
        value = _mapping(snapshot.value, "道藏实例")
        if _text(value.get("编号"), "道藏实例.编号") != normalized_content_id:
            raise AssetStateError("道藏状态键与编号不一致")
        stored_grade = self.grade(_text(value.get("品级"), "道藏实例.品级"))
        if stored_grade.grade_id != normalized_grade_id:
            raise AssetStateError(
                f"道藏中的这门功法是{stored_grade.name}，请按{stored_grade.name}装配"
            )
        return CultivationOwnership(
            normalized_category,
            normalized_content_id,
            _entity_name(self._data, normalized_category, normalized_content_id),
            stored_grade,
            snapshot.version,
        )

    async def plan_cultivation_acquisitions(
        self,
        user_id: str,
        acquisitions: Sequence[CultivationAcquisition],
    ) -> CultivationAcquisitionPlan:
        """把功法、真意或气机取得结果转换为唯一所有权变更。"""

        self._require_initialized()
        normalized_user_id = _required_text(user_id, "user_id")
        normalized: list[tuple[str, str, AssetGrade]] = []
        for acquisition in acquisitions:
            category = _required_text(acquisition.category, "修行取得.类别")
            if category != "功法":
                raise AssetStateError(f"只有功法可以收入道藏：{category}")
            content_id = _required_text(acquisition.content_id, "修行取得.编号")
            record = self._data.entity_record(category, content_id)
            if record.number_category != category:
                raise AssetStateError("修行取得编号类别不匹配")
            normalized.append((category, content_id, self.grade(acquisition.grade_id)))
        if not normalized:
            return CultivationAcquisitionPlan((), ())

        keys = tuple(
            dict.fromkeys(
                _cultivation_state_key(category, content_id, grade.grade_id)
                for category, content_id, grade in normalized
            )
        )
        snapshots = await self._database.get_many(
            tuple(
                StateAddress(normalized_user_id, "cultivation_library", key)
                for key in keys
            )
        )
        existing = {snapshot.address.state_key: snapshot for snapshot in snapshots}
        pending: dict[str, tuple[str, str, AssetGrade]] = {}
        results: list[CultivationAcquisitionResult] = []
        for category, content_id, grade in normalized:
            key = _cultivation_state_key(category, content_id, grade.grade_id)
            current = pending.get(key)
            if current is None and key in existing:
                value = _mapping(existing[key].value, f"cultivation_library/{key}")
                _expect_key(existing[key], content_id)
                if _text(value.get("编号"), "功法所有权.编号") != content_id:
                    raise AssetStateError("功法所有权状态键与编号不一致")
                current = (category, content_id, self.grade(value.get("品级")))
            if current is None:
                outcome = "新得"
                pending[key] = (category, content_id, grade)
            elif grade.order > current[2].order:
                outcome = "升品"
                pending[key] = (category, content_id, grade)
            else:
                outcome = "复悟"
            results.append(
                CultivationAcquisitionResult(
                    category,
                    content_id,
                    _entity_name(self._data, category, content_id),
                    grade,
                    outcome,
                )
            )
        operations = tuple(
            StateMutation(
                normalized_user_id,
                "cultivation_library",
                key,
                {"编号": content_id, "品级": grade.grade_id},
                existing[key].version if key in existing else 0,
            )
            for key, (_, content_id, grade) in pending.items()
        )
        return CultivationAcquisitionPlan(tuple(results), operations)

    async def cultivation_reserve_stack(
        self,
        user_id: str,
        category: str,
        content_id: str,
        grade_id: str,
    ) -> CultivationReserveStack | None:
        """取得一类待装入人物槽位的真意或气机储备。"""

        self._require_initialized()
        normalized_user_id = _required_text(user_id, "user_id")
        normalized_category = _required_text(category, "修行资粮类别")
        if normalized_category not in _CULTIVATION_RESERVE_CATEGORIES:
            raise AssetStateError("修行资粮只能是真意或气机")
        normalized_content_id = _required_text(content_id, "修行资粮编号")
        record = self._data.entity_record(normalized_category, normalized_content_id)
        if record.number_category != normalized_category:
            raise AssetStateError("修行资粮编号类别不匹配")
        grade = self.grade(grade_id)
        key = f"{normalized_content_id}:{grade.grade_id}"
        snapshot = await self._database.get(
            StateAddress(normalized_user_id, "cultivation_reserve", key)
        )
        if snapshot is None:
            return None
        value = _mapping(snapshot.value, f"cultivation_reserve/{key}")
        _expect_key(snapshot, key)
        if _text(value.get("类别"), "修行资粮.类别") != normalized_category:
            raise AssetStateError("修行资粮状态键与类别不一致")
        if _text(value.get("编号"), "修行资粮.编号") != normalized_content_id:
            raise AssetStateError("修行资粮状态键与编号不一致")
        stored_grade = self.grade(_text(value.get("品级"), "修行资粮.品级"))
        if stored_grade.grade_id != grade.grade_id:
            raise AssetStateError("修行资粮状态键与品级不一致")
        return CultivationReserveStack(
            normalized_category,
            normalized_content_id,
            _entity_name(self._data, normalized_category, normalized_content_id),
            stored_grade,
            _positive_int(value.get("数量"), "修行资粮.数量"),
            snapshot.version,
        )

    async def plan_cultivation_reserve_change(
        self,
        user_id: str,
        *,
        category: str,
        content_id: str,
        grade_id: str,
        quantity_delta: int,
    ) -> CultivationReserveChangePlan:
        """生成一类真意或气机储备的原子增减。"""

        if (
            isinstance(quantity_delta, bool)
            or not isinstance(quantity_delta, int)
            or quantity_delta == 0
        ):
            raise AssetStateError("修行资粮变化数量必须是非零整数")
        normalized_user_id = _required_text(user_id, "user_id")
        normalized_category = _required_text(category, "修行资粮类别")
        normalized_content_id = _required_text(content_id, "修行资粮编号")
        grade = self.grade(grade_id)
        current = await self.cultivation_reserve_stack(
            normalized_user_id,
            normalized_category,
            normalized_content_id,
            grade.grade_id,
        )
        before = current.quantity if current is not None else 0
        after = before + quantity_delta
        if after < 0:
            raise AssetStateError(
                f"{grade.name}{_entity_name(self._data, normalized_category, normalized_content_id)}"
                f"储备不足：现有{before}，需要{-quantity_delta}"
            )
        key = f"{normalized_content_id}:{grade.grade_id}"
        name = _entity_name(self._data, normalized_category, normalized_content_id)
        stack = current or CultivationReserveStack(
            normalized_category,
            normalized_content_id,
            name,
            grade,
            0,
            0,
        )
        value = (
            {
                "类别": normalized_category,
                "编号": normalized_content_id,
                "品级": grade.grade_id,
                "数量": after,
            }
            if after
            else None
        )
        return CultivationReserveChangePlan(
            stack,
            before,
            after,
            StateMutation(
                normalized_user_id,
                "cultivation_reserve",
                key,
                value,
                current.version if current is not None else 0,
            ),
        )

    async def law_reserve_stack(self, user_id: str, law_id: str) -> LawReserveStack:
        """取得玩家器藏中的一类待覆炼器律。"""

        self._require_initialized()
        normalized_user_id = _required_text(user_id, "user_id")
        normalized_law_id = _required_text(law_id, "器律编号")
        law = self._data.entity("器律", normalized_law_id)
        snapshot = await self._database.get(
            StateAddress(normalized_user_id, "law_reserve", normalized_law_id)
        )
        if snapshot is None:
            raise AssetStateError("器藏中没有该器律")
        value = _mapping(snapshot.value, "器藏实例")
        if _text(value.get("编号"), "器藏实例.编号") != normalized_law_id:
            raise AssetStateError("器藏状态键与编号不一致")
        return LawReserveStack(
            normalized_law_id,
            _required_entity_text(law, "名称", f"器律 {normalized_law_id}"),
            _required_entity_text(law, "器阶", f"器律 {normalized_law_id}"),
            _positive_int(value.get("数量"), "器藏实例.数量"),
            snapshot.version,
        )

    async def plan_law_reserve_consumption(
        self, user_id: str, law_id: str
    ) -> LawReserveChangePlan:
        """为覆炼事务生成一份共享器藏扣除。"""

        stack = await self.law_reserve_stack(user_id, law_id)
        after = stack.quantity - 1
        return LawReserveChangePlan(
            stack,
            after,
            StateMutation(
                _required_text(user_id, "user_id"),
                "law_reserve",
                stack.law_id,
                {"编号": stack.law_id, "数量": after} if after else None,
                stack.version,
            ),
        )

    async def plan_law_reserve_acquisition(
        self, user_id: str, law_id: str, quantity: int = 1
    ) -> LawReserveAcquisitionPlan:
        """为炼器事务生成一类器律的器藏增量。"""

        self._require_initialized()
        normalized_user_id = _required_text(user_id, "user_id")
        normalized_law_id = _required_text(law_id, "器律编号")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise AssetStateError("器律取得数量必须是正整数")
        law = self._data.entity("器律", normalized_law_id)
        name = _required_entity_text(law, "名称", f"器律 {normalized_law_id}")
        stage = _required_entity_text(law, "器阶", f"器律 {normalized_law_id}")
        snapshot = await self._database.get(
            StateAddress(normalized_user_id, "law_reserve", normalized_law_id)
        )
        before = 0
        version = 0
        if snapshot is not None:
            value = _mapping(snapshot.value, "器藏实例")
            if _text(value.get("编号"), "器藏实例.编号") != normalized_law_id:
                raise AssetStateError("器藏状态键与编号不一致")
            before = _positive_int(value.get("数量"), "器藏实例.数量")
            version = snapshot.version
        after = before + quantity
        return LawReserveAcquisitionPlan(
            normalized_law_id,
            name,
            stage,
            before,
            after,
            StateMutation(
                normalized_user_id,
                "law_reserve",
                normalized_law_id,
                {"编号": normalized_law_id, "数量": after},
                version,
            ),
        )

    async def plan_formation_reserve_acquisition(
        self,
        user_id: str,
        formation_id: str,
        grade_id: str,
        *,
        materials: Mapping[str, str] | None = None,
        treasure_id: str = "",
        modifiers: Mapping[str, str] | None = None,
    ) -> FormationReserveAcquisitionPlan:
        """为炼阵事务生成固定品阵法增量或独立圣品实例。"""

        self._require_initialized()
        normalized_user_id = _required_text(user_id, "user_id")
        normalized_formation_id = _required_text(formation_id, "阵法编号")
        formation = self._data.entity("阵法", normalized_formation_id)
        name = _required_entity_text(
            formation, "名称", f"阵法 {normalized_formation_id}"
        )
        grade = self.grade(grade_id)
        normalized_treasure_id = str(treasure_id or "").strip()
        normalized_modifiers = {
            _required_text(key, "阵法灵宝效果.字段"): _required_text(
                value, f"阵法灵宝效果.{key}"
            )
            for key, value in (modifiers or {}).items()
        }
        if bool(normalized_treasure_id) != bool(normalized_modifiers):
            raise AssetStateError("阵法灵宝编号和效果必须同时存在或同时为空")
        if grade.grade_id == "05":
            values = {
                key: _required_text(value, f"圣品阵法.投入.{key}")
                for key, value in (materials or {}).items()
            }
            if set(values) != {"兽宝", "灵矿", "灵植"}:
                raise AssetStateError("圣品阵法必须完整保存兽宝、灵矿和灵植投入")
            state_key = uuid4().hex
            stack = FormationReserveStack(
                state_key,
                normalized_formation_id,
                name,
                grade.grade_id,
                grade.name,
                1,
                tuple((key, values[key]) for key in ("兽宝", "灵矿", "灵植")),
                normalized_treasure_id,
                tuple(sorted(normalized_modifiers.items())),
                0,
            )
            return FormationReserveAcquisitionPlan(
                stack,
                0,
                1,
                StateMutation(
                    normalized_user_id,
                    "formation_reserve",
                    state_key,
                    {
                        "阵法编号": normalized_formation_id,
                        "品级": grade.grade_id,
                        "投入": values,
                        "灵宝编号": normalized_treasure_id,
                        "灵宝效果": normalized_modifiers,
                    },
                    0,
                ),
            )
        if materials:
            raise AssetStateError("天地玄黄阵法不能保存额外材料投入")
        variant = normalized_treasure_id or "无灵宝"
        state_key = f"{normalized_formation_id}:{grade.grade_id}:{variant}"
        snapshot = await self._database.get(
            StateAddress(normalized_user_id, "formation_reserve", state_key)
        )
        before = 0
        version = 0
        if snapshot is not None:
            value = _mapping(snapshot.value, f"formation_reserve/{state_key}")
            if _text(value.get("阵法编号"), "阵藏.阵法编号") != normalized_formation_id:
                raise AssetStateError("阵藏状态键与阵法编号不一致")
            stored_grade = self.grade(_text(value.get("品级"), "阵藏.品级"))
            if stored_grade.grade_id != grade.grade_id:
                raise AssetStateError("阵藏状态键与品级不一致")
            if str(value.get("灵宝编号") or "").strip() != normalized_treasure_id:
                raise AssetStateError("阵藏状态键与灵宝编号不一致")
            if {
                str(key): str(raw)
                for key, raw in _mapping(value.get("灵宝效果"), "阵藏.灵宝效果").items()
            } != normalized_modifiers:
                raise AssetStateError("阵藏堆叠包含不同的灵宝效果")
            before = _positive_int(value.get("数量"), "阵藏.数量")
            version = snapshot.version
        after = before + 1
        stack = FormationReserveStack(
            state_key,
            normalized_formation_id,
            name,
            grade.grade_id,
            grade.name,
            after,
            (),
            normalized_treasure_id,
            tuple(sorted(normalized_modifiers.items())),
            version,
        )
        return FormationReserveAcquisitionPlan(
            stack,
            before,
            after,
            StateMutation(
                normalized_user_id,
                "formation_reserve",
                state_key,
                {
                    "阵法编号": normalized_formation_id,
                    "品级": grade.grade_id,
                    "数量": after,
                    "灵宝编号": normalized_treasure_id,
                    "灵宝效果": normalized_modifiers,
                },
                version,
            ),
        )

    async def formation_reserve_stack(
        self, user_id: str, state_key: str
    ) -> FormationReserveStack:
        """按阵藏条目键读取固定品堆叠或圣品独立实例。"""

        self._require_initialized()
        normalized_user_id = _required_text(user_id, "user_id")
        normalized_key = _required_text(state_key, "阵藏条目")
        snapshot = await self._database.get(
            StateAddress(normalized_user_id, "formation_reserve", normalized_key)
        )
        if snapshot is None:
            raise AssetStateError("阵藏中没有该阵法")
        value = _mapping(snapshot.value, f"formation_reserve/{normalized_key}")
        formation_id = _text(value.get("阵法编号"), "阵藏.阵法编号")
        formation = self._data.entity("阵法", formation_id)
        name = _required_entity_text(formation, "名称", f"阵法 {formation_id}")
        grade = self.grade(_text(value.get("品级"), "阵藏.品级"))
        treasure_id = str(value.get("灵宝编号") or "").strip()
        raw_modifiers = _mapping(value.get("灵宝效果"), "阵藏.灵宝效果")
        modifiers = tuple(
            sorted(
                (
                    _required_text(key, "阵藏.灵宝效果.字段"),
                    _required_text(raw, f"阵藏.灵宝效果.{key}"),
                )
                for key, raw in raw_modifiers.items()
            )
        )
        if bool(treasure_id) != bool(modifiers):
            raise AssetStateError("阵藏灵宝编号和效果不完整")
        if grade.grade_id == "05":
            raw_materials = _mapping(value.get("投入"), "圣品阵法.投入")
            materials = tuple(
                (
                    key,
                    _required_text(raw_materials.get(key), f"圣品阵法.投入.{key}"),
                )
                for key in ("兽宝", "灵矿", "灵植")
            )
            quantity = 1
        else:
            variant = treasure_id or "无灵宝"
            if normalized_key != f"{formation_id}:{grade.grade_id}:{variant}":
                raise AssetStateError("固定品阵藏状态键与内容不一致")
            materials = ()
            quantity = _positive_int(value.get("数量"), "阵藏.数量")
        return FormationReserveStack(
            normalized_key,
            formation_id,
            name,
            grade.grade_id,
            grade.name,
            quantity,
            materials,
            treasure_id,
            modifiers,
            snapshot.version,
        )

    async def plan_formation_reserve_consumption(
        self, user_id: str, state_key: str
    ) -> FormationReserveConsumptionPlan:
        """为布阵事务生成一份阵藏扣除。"""

        stack = await self.formation_reserve_stack(user_id, state_key)
        after = stack.quantity - 1
        value = None
        if after:
            value = {
                "阵法编号": stack.formation_id,
                "品级": stack.grade_id,
                "数量": after,
                "灵宝编号": stack.treasure_id,
                "灵宝效果": dict(stack.modifiers),
            }
        return FormationReserveConsumptionPlan(
            stack,
            after,
            StateMutation(
                _required_text(user_id, "user_id"),
                "formation_reserve",
                stack.state_key,
                value,
                stack.version,
            ),
        )

    def _entry(
        self,
        snapshot: StateSnapshot,
        equipped: Mapping[tuple[str, str], tuple[str, ...]],
    ) -> AssetEntry:
        state_type = snapshot.address.state_type
        category = self._category_by_state.get(state_type)
        if category is None:
            raise AssetStateError(f"纳戒未登记状态类型：{state_type}")
        value = _mapping(snapshot.value, f"{state_type}/{snapshot.address.state_key}")
        content_id = _text(value.get("编号") or value.get("阵法编号"), "资产编号")
        if state_type == "inventory":
            return self._inventory_entry(snapshot, category, content_id, value)
        if state_type == "cultivation_library":
            return self._cultivation_entry(
                snapshot, category, content_id, value, equipped
            )
        if state_type == "cultivation_reserve":
            return self._cultivation_reserve_entry(
                snapshot, category, content_id, value, equipped
            )
        if state_type == "law_reserve":
            return self._law_entry(snapshot, category, content_id, value)
        if state_type == "formation_reserve":
            return self._formation_entry(snapshot, category, content_id, value)
        return self._knowledge_entry(snapshot, category, content_id)

    def _inventory_entry(
        self,
        snapshot: StateSnapshot,
        category: str,
        content_id: str,
        value: Mapping[str, object],
    ) -> AssetEntry:
        number_category, _ = self._number_identity(content_id)
        grade_id, grade_name = self._grade(value.get("品级"))
        quantity = _positive_int(value.get("数量"), "普通物品.数量")
        _expect_key(snapshot, f"{content_id}:{grade_id}")
        name = _inventory_name(self._data, content_id)
        subcategory = self._match_subcategory(category, "编号类别", number_category)
        return AssetEntry(
            category,
            subcategory,
            content_id,
            snapshot.address.state_key,
            name,
            grade_id,
            grade_name,
            quantity,
            updated_at=snapshot.updated_at,
        )

    def _cultivation_entry(
        self,
        snapshot: StateSnapshot,
        category: str,
        content_id: str,
        value: Mapping[str, object],
        equipped: Mapping[tuple[str, str], tuple[str, ...]],
    ) -> AssetEntry:
        number_category, _ = self._number_identity(content_id)
        if number_category != "功法":
            raise AssetStateError(f"道藏包含非法编号：{content_id}")
        grade_id, grade_name = self._grade(value.get("品级"))
        _expect_key(
            snapshot, _cultivation_state_key(number_category, content_id, grade_id)
        )
        name = _entity_name(self._data, number_category, content_id)
        subcategory = self._match_subcategory(category, "编号类别", number_category)
        return AssetEntry(
            category,
            subcategory,
            content_id,
            snapshot.address.state_key,
            name,
            grade_id,
            grade_name,
            equipped_slots=equipped.get((content_id, grade_id), ()),
            updated_at=snapshot.updated_at,
        )

    def _cultivation_reserve_entry(
        self,
        snapshot: StateSnapshot,
        category: str,
        content_id: str,
        value: Mapping[str, object],
        equipped: Mapping[tuple[str, str], tuple[str, ...]],
    ) -> AssetEntry:
        number_category, _ = self._number_identity(content_id)
        if number_category not in _CULTIVATION_RESERVE_CATEGORIES:
            raise AssetStateError(f"修行资粮包含非法编号：{content_id}")
        if _text(value.get("类别"), "修行资粮.类别") != number_category:
            raise AssetStateError("修行资粮编号类别与正文不一致")
        grade_id, grade_name = self._grade(value.get("品级"))
        quantity = _positive_int(value.get("数量"), "修行资粮.数量")
        _expect_key(snapshot, f"{content_id}:{grade_id}")
        return AssetEntry(
            category,
            self._match_subcategory(category, "编号类别", number_category),
            content_id,
            snapshot.address.state_key,
            _entity_name(self._data, number_category, content_id),
            grade_id,
            grade_name,
            quantity,
            equipped.get((content_id, grade_id), ()),
            updated_at=snapshot.updated_at,
        )

    def _law_entry(
        self,
        snapshot: StateSnapshot,
        category: str,
        content_id: str,
        value: Mapping[str, object],
    ) -> AssetEntry:
        _expect_key(snapshot, content_id)
        law = self._data.entity("器律", content_id)
        name = _required_entity_text(law, "名称", f"器律 {content_id}")
        stage = _required_entity_text(law, "器阶", f"器律 {content_id}")
        quantity = _positive_int(value.get("数量"), "器藏.数量")
        subcategory = self._match_subcategory(category, "器阶", stage)
        return AssetEntry(
            category,
            subcategory,
            content_id,
            snapshot.address.state_key,
            name,
            quantity=quantity,
            updated_at=snapshot.updated_at,
        )

    def _formation_entry(
        self,
        snapshot: StateSnapshot,
        category: str,
        content_id: str,
        value: Mapping[str, object],
    ) -> AssetEntry:
        name = _entity_name(self._data, "阵法", content_id)
        grade_id, grade_name = self._grade(value.get("品级"))
        subcategory = self._match_subcategory(category, "品级", grade_id)
        material_total: int | None = None
        if grade_id == "05":
            materials = _mapping(value.get("投入"), "圣品阵法.投入")
            material_total = sum(
                _nonnegative_decimal(raw, f"圣品阵法.投入.{material}")
                for material, raw in materials.items()
            )
            quantity = 1
        else:
            treasure_id = str(value.get("灵宝编号") or "").strip()
            _expect_key(snapshot, f"{content_id}:{grade_id}:{treasure_id or '无灵宝'}")
            quantity = _positive_int(value.get("数量"), "阵藏.数量")
        return AssetEntry(
            category,
            subcategory,
            content_id,
            snapshot.address.state_key,
            name,
            grade_id,
            grade_name,
            quantity,
            material_total=material_total,
            updated_at=snapshot.updated_at,
        )

    def _knowledge_entry(
        self, snapshot: StateSnapshot, category: str, content_id: str
    ) -> AssetEntry:
        number_category, _ = self._number_identity(content_id)
        if not number_category.endswith("丹药"):
            raise AssetStateError(f"所学包含非丹药编号：{content_id}")
        _expect_key(snapshot, content_id)
        name = _entity_name(self._data, "丹药", content_id)
        subcategory = self._match_subcategory(category, "编号类别", number_category)
        return AssetEntry(
            category,
            subcategory,
            content_id,
            snapshot.address.state_key,
            name,
            updated_at=snapshot.updated_at,
        )

    def _load_prefixes(self) -> None:
        numbering = _mapping(
            self._data.dataset("基础定义").get("编号"), "基础/定义/编号.json"
        )
        rows = _sequence(numbering.get("编号前缀"), "编号.编号前缀")
        prefixes: dict[str, tuple[str, str]] = {}
        for raw in rows:
            row = _mapping(raw, "编号.编号前缀[]")
            prefix = _text(row.get("前缀"), "编号前缀")
            identity = (
                _text(row.get("主体"), f"编号前缀 {prefix}.主体"),
                _text(row.get("类别"), f"编号前缀 {prefix}.类别"),
            )
            if prefix in prefixes:
                raise JsonDataError(f"编号前缀重复：{prefix}")
            prefixes[prefix] = identity
        self._prefixes = prefixes

    def _load_grades(self) -> None:
        rows = _sequence(self._data.dataset("基础定义").get("品级"), "基础/定义/品级.json")
        self._grades = {
            _text(_mapping(raw, "品级[]").get("编号"), "品级.编号"): AssetGrade(
                _text(_mapping(raw, "品级[]").get("编号"), "品级.编号"),
                _text(_mapping(raw, "品级[]").get("名称"), "品级.名称"),
                _positive_int(_mapping(raw, "品级[]").get("阶序"), "品级.阶序"),
                _decimal(_mapping(raw, "品级[]").get("能力倍率"), "品级.能力倍率"),
                _decimal(_mapping(raw, "品级[]").get("价格系数"), "品级.价格系数"),
            )
            for raw in rows
        }
        self._grade_names = {}
        for grade_id, grade in self._grades.items():
            names = {grade.name, grade.name.removesuffix("品")}
            for name in names:
                normalized = _normalize(name)
                existing = self._grade_names.get(normalized)
                if existing is not None and existing != grade_id:
                    raise JsonDataError(f"品级简称重复：{name}")
                self._grade_names[normalized] = grade_id
        self._grade_drop_weights = {
            _text(_mapping(raw, "品级[]").get("编号"), "品级.编号"): 1.0
            / _positive_int(_mapping(raw, "品级[]").get("权重"), "品级.权重")
            for raw in rows
        }

    def _load_categories(self, value: object) -> None:
        rows = _sequence(value, "纳戒.大类")
        categories: list[AssetCategory] = []
        states: dict[str, str] = {}
        rules: dict[tuple[str, str], Mapping[str, object]] = {}
        names: set[str] = set()
        for raw in rows:
            row = _mapping(raw, "纳戒.大类[]")
            name = _text(row.get("名称"), "纳戒.大类.名称")
            if name in names:
                raise JsonDataError(f"纳戒大类重复：{name}")
            names.add(name)
            state_type = _text(row.get("状态类型"), f"纳戒.{name}.状态类型")
            if state_type not in _STATE_TYPES or state_type in states:
                raise JsonDataError(f"纳戒状态类型非法或重复：{state_type}")
            states[state_type] = name
            subcategories: list[AssetSubcategory] = []
            subcategory_names: set[str] = set()
            for sub_raw in _sequence(row.get("小类"), f"纳戒.{name}.小类"):
                sub = _mapping(sub_raw, f"纳戒.{name}.小类[]")
                sub_name = _text(sub.get("名称"), f"纳戒.{name}.小类.名称")
                if sub_name in subcategory_names:
                    raise JsonDataError(f"纳戒小类重复：{name}/{sub_name}")
                subcategory_names.add(sub_name)
                match_fields = {
                    str(key): raw_value
                    for key, raw_value in sub.items()
                    if key != "名称"
                }
                if len(match_fields) != 1:
                    raise JsonDataError(f"纳戒小类必须只有一个归类条件：{sub_name}")
                subcategories.append(AssetSubcategory(sub_name))
                rules[(name, sub_name)] = match_fields
            categories.append(
                AssetCategory(
                    name,
                    _text(row.get("图标"), f"纳戒.{name}.图标"),
                    tuple(subcategories),
                )
            )
        if set(states) != _STATE_TYPES:
            raise JsonDataError("纳戒展示没有完整覆盖玩家资产状态类型")
        self._categories = tuple(categories)
        self._category_by_state = states
        self._subcategory_rules = rules

    def _validate_cultivation_rules(self) -> None:
        rules = _mapping(
            self._data.dataset("角色规则").get("修行所得"),
            "角色/规则/修行/修行所得.json",
        )
        policy = _mapping(rules.get("功法取得"), "修行所得.功法取得")
        identity = tuple(
            _text(field, "修行所得.功法取得.唯一实例[]")
            for field in _sequence(
                policy.get("唯一实例"), "修行所得.功法取得.唯一实例"
            )
        )
        expected = {
            "相同或更低品级": "复悟",
            "更高品级": "覆盖并同步已装配槽位",
            "复悟收益": "无",
            "积累": "无",
        }
        if identity != ("编号",) or any(
            policy.get(key) != value for key, value in expected.items()
        ):
            raise JsonDataError("功法取得规则与道藏唯一所有权契约不一致")
        acquisitions = tuple(
            _mapping(value, "修行所得.取得[]")
            for value in _sequence(rules.get("取得"), "修行所得.取得")
        )
        reserve = next(
            (
                value
                for value in acquisitions
                if tuple(value.get("类别") or ()) == ("真意", "气机")
            ),
            None,
        )
        if reserve is None or reserve.get("进入") != "修行资粮" or reserve.get(
            "相同实例"
        ) != "累计数量":
            raise JsonDataError("真意与气机取得规则必须进入修行资粮并累计数量")
        equip = _mapping(rules.get("装配"), "修行所得.装配")
        if equip.get("真意气机消耗数量") != 1 or equip.get(
            "被替换真意气机"
        ) != "消失":
            raise JsonDataError("真意与气机装配必须消耗一份且替换后消失")

    def _number_identity(self, content_id: str) -> tuple[str, str]:
        identity = self._prefixes.get(content_id[:2])
        if identity is None:
            raise AssetStateError(f"资产编号前缀未定义：{content_id}")
        subject, category = identity
        return (subject if category in {"丹药"} else category, category)

    def _grade(self, value: object) -> tuple[str, str]:
        grade_id = _text(value, "资产品级")
        grade = self._grades.get(grade_id)
        if grade is None:
            raise AssetStateError(f"资产使用未知品级：{grade_id}")
        return grade_id, grade.name

    def _match_subcategory(self, category: str, field: str, value: str) -> str:
        matches = [
            subcategory
            for (large, subcategory), rule in self._subcategory_rules.items()
            if large == category and rule.get(field) == value
        ]
        if len(matches) != 1:
            raise AssetStateError(
                f"纳戒资产必须且只能命中一个小类：{category}/{field}={value}"
            )
        return matches[0]

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("玩家资产核心微服务尚未初始化")


def _equipped_content(
    snapshots: Sequence[StateSnapshot],
) -> Mapping[tuple[str, str], tuple[str, ...]]:
    cultivation = next(
        (
            snapshot.value
            for snapshot in snapshots
            if snapshot.address.state_type == "cultivation"
            and snapshot.address.state_key == "main"
        ),
        None,
    )
    if cultivation is None:
        return {}
    result: dict[tuple[str, str], list[str]] = {}
    for category in ("功法", "真意", "气机"):
        slots = _sequence(
            cultivation.get(category), f"修行槽.{category}", allow_empty=True
        )
        for index, raw in enumerate(slots, start=1):
            if raw is None:
                continue
            entry = _mapping(raw, f"修行槽.{category}[{index}]")
            key = (
                _text(entry.get("编号"), "装配编号"),
                _text(entry.get("品级"), "装配品级"),
            )
            result.setdefault(key, []).append(f"{category}{index}")
    return {key: tuple(values) for key, values in result.items()}


def _sort_rules(value: object) -> AssetSortRules:
    rules = _mapping(value, "纳戒.排序")
    equipped_first = rules.get("已装配优先")
    if not isinstance(equipped_first, bool):
        raise JsonDataError("纳戒.排序.已装配优先必须是布尔值")
    grade_direction = _direction(rules.get("品级"), "纳戒.排序.品级")
    content_id_direction = _direction(rules.get("编号"), "纳戒.排序.编号")
    holy_formation_direction = _text(rules.get("圣品阵法"), "纳戒.排序.圣品阵法")
    if holy_formation_direction not in {"炼制时间升序", "炼制时间降序"}:
        raise JsonDataError("纳戒.排序.圣品阵法只能是炼制时间升序或炼制时间降序")
    return AssetSortRules(
        equipped_first=equipped_first,
        grade_descending=grade_direction == "降序",
        content_id_descending=content_id_direction == "降序",
        holy_formation_newest_first=holy_formation_direction == "炼制时间降序",
    )


def _direction(value: object, label: str) -> str:
    direction = _text(value, label)
    if direction not in {"升序", "降序"}:
        raise JsonDataError(f"{label}只能是升序或降序")
    return direction


def _entity_name(data: JsonDataService, section: str, content_id: str) -> str:
    try:
        value = data.entity(section, content_id)
    except JsonDataError as exc:
        raise AssetStateError(f"资产引用不存在：{section} {content_id}") from exc
    return _required_entity_text(value, "名称", f"{section} {content_id}")


#: 能进纳戒的数据集。解析只此一处——原先 5 处各写死「基础物品」，于是任何非基础物品的
#: 库存条目（丹药）一读栈就抛「实体不存在」。数据里每个物品只属于一个数据集，依次试即可。
INVENTORY_SECTIONS = ("基础物品", "丹药")


def _inventory_name(data: JsonDataService, item_id: str) -> str:
    """按能进纳戒的数据集依次解析物品名。"""

    for section in INVENTORY_SECTIONS:
        try:
            return _entity_name(data, section, item_id)
        except (JsonDataError, AssetStateError):
            continue
    raise AssetStateError(f"纳戒物品不存在：{item_id}")


def _required_entity_text(value: Mapping[str, object], field: str, label: str) -> str:
    try:
        return _text(value.get(field), f"{label}.{field}")
    except AssetStateError as exc:
        raise AssetStateError(str(exc)) from exc


def _expect_key(snapshot: StateSnapshot, expected: str) -> None:
    if snapshot.address.state_key != expected:
        raise AssetStateError(
            f"资产状态键与正文不符：{snapshot.address.state_type}/"
            f"{snapshot.address.state_key} != {expected}"
        )


def _cultivation_state_key(category: str, content_id: str, grade_id: str) -> str:
    return content_id if category == "功法" else f"{content_id}:{grade_id}"


def _mapping(value: object, label: str) -> Mapping[str, object]:
    return mapping(value, label, error=AssetStateError)


def _sequence(
    value: object, label: str, *, allow_empty: bool = False
) -> tuple[object, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise AssetStateError(f"{label}必须是数组")
    result = tuple(value)
    if not result and not allow_empty:
        raise AssetStateError(f"{label}不能为空")
    return result


def _text(value: object, label: str) -> str:
    return nonempty_text(value, label, error=AssetStateError)


def _required_text(value: object, label: str) -> str:
    return nonempty_text(value, label, error=InventoryChangeError)


def _normalize(value: object) -> str:
    return "".join(str(value or "").split()).casefold()


def _decimal(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise JsonDataError(f"{label}必须是十进制数") from exc
    if not result.is_finite() or result <= 0:
        raise JsonDataError(f"{label}必须大于0")
    return result


def _positive_int(value: object, label: str) -> int:
    return positive_int(value, label, error=AssetStateError)


def _nonnegative_decimal(value: object, label: str) -> int:
    text = _text(value, label)
    if not text.isdecimal():
        raise AssetStateError(f"{label}必须是非负十进制字符串")
    return int(text)


__all__ = ["AssetService"]
