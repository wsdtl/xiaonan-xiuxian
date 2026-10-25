"""解释基础物品升阶规则，产出只读报价与库存变更计划。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from game.core.asset import AssetService, InventoryAdjustment
from game.core.data import (
    JsonDataError,
    JsonDataService,
    mapping as _mapping,
    number as _number,
    positive_int as _positive_int,
    sequence as _sequence,
    strict_text as _text,
)

from .contracts import (
    MaterialPlan,
    MaterialRequirement,
    PromotionError,
    PromotionStatus,
    UpgradeLine,
    UpgradePlan,
)


class PromotionService:
    """升阶规则、报价与材料缺口方案的唯一解释入口。"""

    def __init__(self, data: JsonDataService, asset: AssetService) -> None:
        self._data = data
        self._asset = asset
        self._initialized = False
        self._allowed_categories: tuple[str, ...] = ()
        self._max_grade_id = ""
        self._allow_jump = False
        self._every = 0
        self._batch_limit = 0
        self._line_limit = 0

    def initialize(self) -> PromotionStatus:
        if self._initialized:
            raise RuntimeError("升阶核心微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据微服务必须先于升阶核心启动")
        if not self._asset.status().initialized:
            raise RuntimeError("玩家资产核心必须先于升阶核心启动")
        rules = _mapping(
            self._data.dataset("基础物品升阶规则").get("升阶"),
            "基础物品升阶规则",
        )
        self._allowed_categories = tuple(
            _text(raw, "基础物品升阶规则.允许类别[]")
            for raw in _sequence(rules.get("允许类别"), "基础物品升阶规则.允许类别")
        )
        if not self._allowed_categories or len(set(self._allowed_categories)) != len(
            self._allowed_categories
        ):
            raise JsonDataError("升阶允许类别不能为空或重复")
        for category in self._allowed_categories:
            if category not in {"灵植", "灵矿", "兽宝"}:
                raise JsonDataError(f"升阶只允许基础材料类别：{category}")
        max_grade = self._asset.grade(
            _text(rules.get("目标品级上限"), "基础物品升阶规则.目标品级上限")
        )
        self._max_grade_id = max_grade.grade_id
        allow_jump = rules.get("允许跳级")
        if not isinstance(allow_jump, bool):
            raise JsonDataError("基础物品升阶规则.允许跳级必须是布尔值")
        self._allow_jump = allow_jump
        every = _mapping(rules.get("消耗"), "基础物品升阶规则.消耗").get("每件")
        self._every = _positive_int(every, "基础物品升阶规则.消耗.每件")
        self._batch_limit = _positive_int(
            rules.get("批量上限"), "基础物品升阶规则.批量上限"
        )
        self._line_limit = _positive_int(
            rules.get("方案行数上限"), "基础物品升阶规则.方案行数上限"
        )
        self._validate_no_arbitrage()
        self._initialized = True
        return self.status()

    def status(self) -> PromotionStatus:
        return PromotionStatus(
            self._initialized,
            self._allowed_categories,
            self._max_grade_id,
            self._batch_limit,
        )

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("升阶核心微服务尚未初始化")

    def _unit_cost(self, target_grade_id: str) -> int:
        units = self._asset.spirit_stone_units()
        try:
            face = units[target_grade_id]
        except KeyError as exc:
            raise PromotionError(f"目标品级没有灵石面值：{target_grade_id}") from exc
        return face * self._every

    def _item(self, item_id: str) -> tuple[Mapping[str, object], str]:
        normalized = _text(item_id, "升阶物品编号")
        try:
            value = self._data.entity("基础物品", normalized)
        except JsonDataError as exc:
            raise PromotionError(f"基础物品不存在：{normalized}") from exc
        record = self._data.entity_record("基础物品", normalized)
        category = str(record.number_category or "")
        if category not in self._allowed_categories:
            raise PromotionError(f"该类别不能升阶：{category or '未知'}")
        if str(value.get("名称") or "").strip() == "":
            raise PromotionError(f"基础物品缺少名称：{normalized}")
        return value, category

    def _pair(self, source_grade_id: str, target_grade_id: str):
        source = self._asset.grade(source_grade_id)
        target = self._asset.grade(target_grade_id)
        if source.order >= target.order:
            raise PromotionError("目标品级必须高于来源品级")
        if target.order > self._asset.grade(self._max_grade_id).order:
            raise PromotionError(f"升阶目标不能超过{self._asset.grade(self._max_grade_id).name}")
        if not self._allow_jump and target.order != source.order + 1:
            raise PromotionError("升阶规则不允许跳级")
        return source, target

    def _quantity(self, quantity: int) -> int:
        value = _positive_int(quantity, "升阶数量")
        if value > self._batch_limit:
            raise PromotionError(f"一次最多升阶{self._batch_limit}件")
        return value

    async def plan_upgrade(
        self,
        user_id: str,
        item_id: str,
        source_grade_id: str,
        target_grade_id: str,
        quantity: int,
    ) -> UpgradePlan:
        """单件（可多件同编号/同来源品级）升阶计划；只出计划，不提交。"""

        self._require_initialized()
        value, _ = self._item(item_id)
        source, target = self._pair(source_grade_id, target_grade_id)
        count = self._quantity(quantity)
        stacks = await self._asset.inventory_stacks(user_id, item_id)
        available = sum(
            stack.quantity
            for stack in stacks
            if stack.grade.grade_id == source.grade_id
        )
        if available < count:
            raise PromotionError(
                f"{source.name}{value.get('名称')}数量不足：现有{available}，需要{count}"
            )
        unit = self._unit_cost(target.grade_id)
        total = unit * count
        before = await self._asset.spirit_stone_balance(user_id)
        after = before - total
        if after < 0:
            raise PromotionError(f"灵石不足：现有{before}，需要{total}")
        item_plan = await self._asset.plan_inventory_changes(
            user_id,
            (
                InventoryAdjustment(item_id, source.grade_id, -count),
                InventoryAdjustment(item_id, target.grade_id, count),
            ),
        )
        stone_plan = await self._asset.plan_spirit_stone_change(user_id, -total)
        line = UpgradeLine(
            item_id,
            _text(value.get("名称"), "升阶物品名称"),
            source.grade_id,
            source.name,
            target.grade_id,
            target.name,
            count,
            unit,
            total,
        )
        return UpgradePlan(
            (line,),
            total,
            before,
            after,
            True,
            item_plan.operations + stone_plan.operations,
        )

    async def plan_requirements(
        self,
        user_id: str,
        requirements: Sequence[MaterialRequirement],
        *,
        line_limit: int | None = None,
    ) -> MaterialPlan:
        """按炼制材料缺口给出升阶建议；只读，不提交。"""

        self._require_initialized()
        if not requirements:
            raise PromotionError("升阶方案至少需要一条材料要求")
        normalized_requirements = tuple(self._requirement(raw) for raw in requirements)
        limit = self._line_limit if line_limit is None else _positive_int(line_limit, "方案行数")
        snapshot = await self._asset.snapshot(user_id)
        available: dict[tuple[str, str], int] = {}
        for entry in snapshot.entries:
            if entry.category != "基础物品" or entry.subcategory not in self._allowed_categories:
                continue
            key = (entry.content_id, entry.grade_id)
            available[key] = available.get(key, 0) + entry.quantity
        lines: list[UpgradeLine] = []
        missing: list[MaterialRequirement] = []
        total = 0
        for requirement in normalized_requirements:
            need = requirement.quantity
            keys = [key for key in available if available[key] > 0]
            # 先用已经达到最低品级的库存；同品级优先低阶，保留高阶。
            free = sorted(
                (
                    key
                    for key in keys
                    if (not requirement.item_id or key[0] == requirement.item_id)
                    and self._data.entity_record("基础物品", key[0]).number_category
                    == requirement.category
                    and self._asset.grade(key[1]).order
                    >= self._asset.grade(requirement.minimum_grade_id).order
                ),
                key=lambda key: (self._asset.grade(key[1]).order, key[0]),
            )
            for item_id, grade_id in free:
                if need <= 0:
                    break
                take = min(available[(item_id, grade_id)], need)
                available[(item_id, grade_id)] -= take
                need -= take
            if need <= 0:
                continue
            # 再用低品库存升到最低品级；低品先升，保留高品。
            target = self._asset.grade(requirement.minimum_grade_id)
            lower = sorted(
                (
                    key
                    for key in keys
                    if (not requirement.item_id or key[0] == requirement.item_id)
                    and self._data.entity_record("基础物品", key[0]).number_category
                    == requirement.category
                    and self._asset.grade(key[1]).order < target.order
                ),
                key=lambda key: (self._asset.grade(key[1]).order, key[0]),
            )
            for item_id, grade_id in lower:
                if need <= 0:
                    break
                take = min(available[(item_id, grade_id)], need)
                if take <= 0:
                    continue
                source = self._asset.grade(grade_id)
                item_value = self._data.entity("基础物品", item_id)
                unit = self._unit_cost(target.grade_id)
                lines.append(
                    UpgradeLine(
                        item_id,
                        _text(item_value.get("名称"), "升阶物品名称"),
                        source.grade_id,
                        source.name,
                        target.grade_id,
                        target.name,
                        take,
                        unit,
                        unit * take,
                    )
                )
                total += unit * take
                available[(item_id, grade_id)] -= take
                need -= take
            if need > 0:
                missing.append(
                    MaterialRequirement(
                        requirement.category,
                        requirement.item_id,
                        need,
                        requirement.minimum_grade_id,
                    )
                )
        if len(lines) > limit:
            raise PromotionError(f"升阶方案超过{limit}条，请拆分或减少数量")
        before = await self._asset.spirit_stone_balance(user_id)
        after = before - total
        return MaterialPlan(
            tuple(lines),
            total,
            before,
            after,
            after >= 0,
            tuple(missing),
            not missing and after >= 0,
        )

    def _requirement(self, raw: MaterialRequirement) -> MaterialRequirement:
        category = _text(raw.category, "材料要求.类别")
        if category not in self._allowed_categories:
            raise PromotionError(f"该类别不能升阶：{category}")
        quantity = _positive_int(raw.quantity, "材料要求.数量")
        minimum = self._asset.grade(raw.minimum_grade_id)
        if raw.item_id:
            value, actual = self._item(raw.item_id)
            if actual != category:
                raise PromotionError(f"材料编号与类别不一致：{raw.item_id}")
        return MaterialRequirement(category, raw.item_id, quantity, minimum.grade_id)

    def _validate_no_arbitrage(self) -> None:
        """固定 1 枚目标品级灵石的规则下，任何来源/目标组合都不能低于价值增量。"""

        grades = self._asset.grades()
        max_order = self._asset.grade(self._max_grade_id).order
        for item_id, value in self._data.entities("基础物品").items():
            record = self._data.entity_record("基础物品", item_id)
            if record.number_category not in self._allowed_categories:
                continue
            reference = _number(value.get("参考价"), f"{item_id}.参考价")
            if reference <= 0:
                raise JsonDataError(f"基础物品参考价必须为正：{item_id}")
            base = Decimal(str(reference))
            for target in grades:
                if target.order > max_order:
                    continue
                cost = Decimal(self._unit_cost(target.grade_id))
                for source in grades:
                    if source.order >= target.order:
                        continue
                    gain = base * (target.price_multiplier - source.price_multiplier)
                    if cost < gain:
                        raise JsonDataError(
                            "升阶面值不足，存在套利："
                            f"{item_id} {source.name}→{target.name} "
                            f"成本{cost} 价值增量{gain}"
                        )


__all__ = ["PromotionService"]
