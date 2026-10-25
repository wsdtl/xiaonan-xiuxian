"""基础物品升阶的玩法编排：解析、报价、事务与炼制缺口方案。"""

from __future__ import annotations

from collections.abc import Mapping

from game.core.alchemy import AlchemyError, AlchemyService
from game.core.asset import AssetService, AssetStateError
from game.core.asset.ref import ItemRefError, parse_item_ref
from game.core.data import JsonDataError, JsonDataService
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    StateConflictError,
    TransactionCommand,
)
from game.core.forging import ForgingError, ForgingService
from game.core.formation import FormationError, FormationService
from game.core.promotion import (
    MaterialRequirement,
    PromotionError,
    PromotionService,
)

from .contracts import CraftingPlan, MaterialPlanView, ShengjieError, ShengjieResult


class ShengjieFeature:
    """只编排升阶核心与资产核心，不直接读写 SQLite。"""

    def __init__(
        self,
        data: JsonDataService,
        asset: AssetService,
        database: DatabaseService,
        promotion: PromotionService,
        alchemy: AlchemyService,
        forging: ForgingService,
        formation: FormationService,
    ) -> None:
        self._data = data
        self._asset = asset
        self._database = database
        self._promotion = promotion
        self._alchemy = alchemy
        self._forging = forging
        self._formation = formation
        self._copy: Mapping[str, str] = {}
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("升阶玩法已经初始化")
        for ready, label in (
            (self._data.status().loaded, "JSON 数据微服务"),
            (self._asset.status().initialized, "玩家资产核心"),
            (self._database.status().initialized, "核心数据库"),
            (self._promotion.status().initialized, "升阶核心"),
            (self._alchemy.status().initialized, "炼丹核心"),
            (self._forging.status().initialized, "炼器核心"),
            (self._formation.status().initialized, "阵法核心"),
        ):
            if not ready:
                raise RuntimeError(f"{label}必须先于升阶玩法启动")
        display = self._data.dataset("升阶展示").get("升阶")
        raw = display.get("升阶") if isinstance(display, Mapping) else None
        if not isinstance(raw, Mapping):
            raise RuntimeError("升阶展示数据缺少「升阶」对象")
        self._copy = {str(key): str(value) for key, value in raw.items()}
        self._initialized = True

    def copy(self) -> Mapping[str, str]:
        self._require_initialized()
        return self._copy

    async def upgrade_from_text(
        self,
        user_id: str,
        request_id: str,
        source_text: str,
        target_text: str,
        quantity: int = 1,
    ) -> ShengjieResult:
        item_id, source_grade = self._resolve_source(source_text)
        target = self._resolve_target(target_text)
        return await self.upgrade(
            user_id, request_id, item_id, source_grade, target.grade_id, quantity
        )

    async def upgrade(
        self,
        user_id: str,
        request_id: str,
        item_id: str,
        source_grade_id: str,
        target_grade_id: str,
        quantity: int = 1,
    ) -> ShengjieResult:
        self._require_initialized()
        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != "物品升阶":
                raise ShengjieError("请求编号已经用于其他操作")
            payload = committed.payload
            if (
                str(payload.get("物品编号") or "") != item_id
                or str(payload.get("来源品级") or "") != source_grade_id
                or str(payload.get("目标品级") or "") != target_grade_id
                or int(payload.get("数量") or 0) != quantity
            ):
                raise ShengjieError("请求编号已经用于其他升阶")
            return self._result_from_payload(payload, replayed=True)
        try:
            plan = await self._promotion.plan_upgrade(
                user_id, item_id, source_grade_id, target_grade_id, quantity
            )
        except PromotionError as exc:
            raise ShengjieError(str(exc)) from exc
        line = plan.lines[0]
        payload = {
            "物品编号": line.item_id,
            "物品名称": line.item_name,
            "来源品级": line.source_grade_id,
            "来源品级名": line.source_grade_name,
            "目标品级": line.target_grade_id,
            "目标品级名": line.target_grade_name,
            "数量": line.quantity,
            "单件消耗": line.unit_cost,
            "总消耗": line.total_cost,
            "升阶前灵石": plan.spirit_stone_before,
            "升阶后灵石": plan.spirit_stone_after,
        }
        try:
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id,
                    request_id,
                    "物品升阶",
                    plan.operations,
                    payload,
                )
            )
        except StateConflictError as exc:
            raise ShengjieError("库存已经变化，请重新升阶") from exc
        except IdempotencyConflictError as exc:
            raise ShengjieError("请求编号已经用于其他操作") from exc
        return ShengjieResult(
            line.item_id,
            line.item_name,
            line.source_grade_id,
            line.source_grade_name,
            line.target_grade_id,
            line.target_grade_name,
            line.quantity,
            line.unit_cost,
            line.total_cost,
            plan.spirit_stone_before,
            plan.spirit_stone_after,
            receipt.replayed,
        )

    async def plan_crafting(
        self, user_id: str, kind: str, identifier: str, quantity: int = 1
    ) -> CraftingPlan:
        self._require_initialized()
        try:
            if kind == "炼丹":
                name = self._alchemy.recipe_name(identifier)
                requirements = self._alchemy.requirements(identifier, quantity)
                command = "开丹炉 " + name + ("" if quantity == 1 else f" {quantity}")
            elif kind == "炼器":
                name = self._forging.law_name(identifier)
                requirements = self._forging.requirements(identifier, quantity)
                command = "开炉 " + name + ("" if quantity == 1 else f" {quantity}")
            elif kind == "炼阵":
                grade, formation_name = self._formation_grade_and_name(identifier)
                name = self._formation.formation_name(formation_name)
                requirements = self._formation.requirements(
                    name, grade.name, quantity
                )
                command = f"炼阵 {grade.name}{name}"
            else:
                raise ShengjieError("升阶方案目前支持炼丹、炼器、炼阵")
        except (AlchemyError, ForgingError, FormationError, JsonDataError) as exc:
            raise ShengjieError(str(exc)) from exc
        try:
            plan = await self._promotion.plan_requirements(user_id, requirements)
        except PromotionError as exc:
            raise ShengjieError(str(exc)) from exc
        return CraftingPlan(kind, name, plan, command)

    async def plan_material(
        self,
        user_id: str,
        category: str,
        item_text: str,
        target_text: str,
        quantity: int = 1,
    ) -> MaterialPlanView:
        self._require_initialized()
        target = self._resolve_target(target_text)
        item_id = self.resolve_item_id(item_text, category) if item_text else ""
        requirement = MaterialRequirement(
            category, item_id, quantity, target.grade_id
        )
        try:
            plan = await self._promotion.plan_requirements(user_id, (requirement,))
        except PromotionError as exc:
            raise ShengjieError(str(exc)) from exc
        return MaterialPlanView(category, target.grade_id, target.name, plan)

    def resolve_item_id(self, text: str, category: str = "") -> str:
        wanted = str(text or "").strip()
        if not wanted:
            raise ShengjieError("缺少基础物品")
        if wanted.isdigit():
            return wanted
        matches = [
            item_id
            for item_id, value in self._data.entities("基础物品").items()
            if str(value.get("名称") or "") == wanted
            and (
                not category
                or self._data.entity_record("基础物品", item_id).number_category == category
            )
        ]
        if not matches:
            raise ShengjieError(f"未找到基础物品：{wanted}")
        if len(matches) > 1:
            raise ShengjieError(f"同名基础物品不止一个：{wanted}")
        return matches[0]

    def _formation_grade_and_name(self, text: str):
        grades = {grade.name: grade.grade_id for grade in self._asset.grades()}
        grades.update(
            {grade.name.removesuffix("品"): grade.grade_id for grade in self._asset.grades()}
        )
        try:
            ref = parse_item_ref(text, grades=grades)
        except ItemRefError as exc:
            raise ShengjieError(str(exc)) from exc
        if not ref.grade:
            raise ShengjieError("阵法要带品级，例如：升阶方案 炼阵 黄品叠翠盘根阵")
        return self._asset.grade(ref.grade), ref.item

    def _resolve_source(self, text: str) -> tuple[str, str]:
        grades = {
            grade.name: grade.grade_id
            for grade in self._asset.grades()
        }
        grades.update(
            {grade.name.removesuffix("品"): grade.grade_id for grade in self._asset.grades()}
        )
        try:
            ref = parse_item_ref(text, grades=grades)
        except ItemRefError as exc:
            raise ShengjieError(str(exc)) from exc
        if not ref.grade:
            raise ShengjieError("写法要带来源品级，例如：升阶 黄品岩露黄精 圣品")
        grade = self._asset.grade(ref.grade)
        return self.resolve_item_id(ref.item), grade.grade_id

    def _resolve_target(self, text: str):
        normalized = str(text or "").strip()
        if not normalized:
            raise ShengjieError("缺少目标品级")
        try:
            return self._asset.grade(normalized)
        except (AssetStateError, JsonDataError, ValueError) as exc:
            raise ShengjieError(f"未知目标品级：{normalized}") from exc

    def _result_from_payload(
        self, payload: Mapping[str, object], *, replayed: bool
    ) -> ShengjieResult:
        return ShengjieResult(
            str(payload.get("物品编号") or ""),
            str(payload.get("物品名称") or ""),
            str(payload.get("来源品级") or ""),
            str(payload.get("来源品级名") or ""),
            str(payload.get("目标品级") or ""),
            str(payload.get("目标品级名") or ""),
            int(payload.get("数量") or 0),
            int(payload.get("单件消耗") or 0),
            int(payload.get("总消耗") or 0),
            int(payload.get("升阶前灵石") or 0),
            int(payload.get("升阶后灵石") or 0),
            replayed,
        )

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("升阶玩法尚未初始化")


__all__ = ["ShengjieFeature"]
