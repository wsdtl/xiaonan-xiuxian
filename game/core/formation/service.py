"""解释阵法 JSON，并管理炼阵、待战与战斗快照。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from types import MappingProxyType

from game.core.asset import (
    AssetEntry,
    AssetService,
    AssetStateError,
    InventoryAdjustment,
    InventoryChangeError,
    ItemRef,
    ItemRefError,
    format_item_ref,
    parse_item_ref,
)
from game.core.data import (
    ContractSet,
    JsonDataError,
    JsonDataService,
    mapping as _mapping,
    nonempty_text,
    nonnegative_int,
    positive_int,
    positive_int as _positive_int,
    sequence as _sequence,
    speech,
    strict_text,
    strict_text as _text,
)
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    StateAddress,
    StateConflictError,
    StateMutation,
    TransactionCommand,
)
from game.core.innate_treasure import (
    InnateTreasureActivation,
    InnateTreasureService,
    activation_payload,
    treasure_line,
)
from game.core.crafting import (
    CraftCostRules,
    CraftEnvironment,
    current_environment,
    facility_from_payload,
    facility_payload,
    material_quantity,
)
from game.core.location import LocationService
from game.core.promotion import MaterialRequirement
from game.core.world import CraftFacility, WorldService

from .contracts import (
    FormationActivationPlan,
    FormationArmResult,
    FormationAssessment,
    FormationBattleProfile,
    FormationConflictError,
    FormationDefinition,
    FormationDetection,
    FormationEntry,
    FormationCandidate,
    FormationChoiceError,
    FormationError,
    FormationMaterial,
    FormationMaterialError,
    FormationNodeRules,
    FormationOverview,
    FormationPrepared,
    FormationPreview,
    FormationRequirement,
    FormationResult,
    FormationSnapshot,
    FormationStageProfile,
    FormationStatus,
    FormationUnavailableError,
)
from game.core.data import number as _number

_CATEGORIES = ("兽宝", "灵矿", "灵植")
# 品级名一律写全（规则：不许用短名，黄 要写 黄品）；编号映射见下一行，与 data/基础/定义/品级.json 对齐。
_GRADES = ("黄品", "玄品", "地品", "天品", "圣品")
_GRADE_IDS = dict(zip(_GRADES, ("01", "02", "03", "04", "05"), strict=True))
_GRADE_NAMES_BY_ID = {grade_id: name for name, grade_id in _GRADE_IDS.items()}
_PREPARED_STATE = "prepared_formation"
_PREPARED_KEY = "main"
_DETECTION_FIELDS = frozenset(
    {
        "已损失血气",
        "已损失精神",
        "护盾比例",
        "行动条进度",
        "负面状态层数",
        "正面状态层数",
        "冷却中技能",
        "敌我存活人数差",
        "阵核剩余承载比例",
        "本场击杀数",
        "本场死亡数",
        "当前回合数",
        "当前形态",
        "双方等级差",
        "本场触发次数",
        "目标已损失血气",
    }
)


def _detection(raw: Mapping[str, object], formation_id: str) -> FormationDetection | None:
    value = raw.get("检测")
    if value is None:
        return None
    detection = _mapping(value, f"阵法 {formation_id}.检测")
    return FormationDetection(
        field=_text(detection.get("字段"), f"阵法 {formation_id}.检测.字段"),
        relation=_text(detection.get("关系"), f"阵法 {formation_id}.检测.关系"),
        coefficient=float(
            _number(detection.get("系数"), f"阵法 {formation_id}.检测.系数")
        ),
        difficulty=str(detection.get("难度") or ""),
        monitor=str(detection.get("监测") or ""),
    )


class FormationService:
    """阵法定义、材料投入、阵藏转换和战斗快照的唯一入口。"""


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
        self._rules: Mapping[str, object] = MappingProxyType({})
        self._fixed_grades: tuple[str, ...] = ()
        self._unbounded_grade = ""
        self._fixed_costs: Mapping[str, Mapping[str, int]] = MappingProxyType({})
        self._raw_formations: Mapping[str, Mapping[str, object]] = MappingProxyType({})
        self._formations: Mapping[str, FormationDefinition] = MappingProxyType({})
        self._formation_by_name: Mapping[str, str] = MappingProxyType({})
        self._cost_rules: CraftCostRules | None = None
        self._town_max_grade_name = ""
        self._page_limit = 0

    def initialize(self) -> FormationStatus:
        if self._initialized:
            raise RuntimeError("阵法核心微服务已经初始化")
        for ready, label in (
            (self._data.status().loaded, "JSON 数据微服务"),
            (self._database.status().initialized, "核心数据库"),
            (self._asset.status().initialized, "玩家资产核心"),
            (self._world.status().initialized, "世界核心"),
            (self._location.status().initialized, "位置核心"),
            (self._innate_treasure.status().initialized, "先天灵宝核心"),
        ):
            if not ready:
                raise RuntimeError(f"{label}必须先于阵法核心启动")
        self._rules = MappingProxyType(
            dict(_mapping(self._data.dataset("阵法规则").get("炼制"), "阵法规则.炼制"))
        )
        self._grade_rows = MappingProxyType(
            {
                _text(_mapping(raw, "品级[]").get("名称"), "品级.名称"): _mapping(raw, "品级[]")
                for raw in _sequence(
                    self._data.dataset("基础定义").get("品级"), "基础/定义/品级.json"
                )
            }
        )
        for grade_name, grade_row in self._grade_rows.items():
            _positive_int(
                grade_row.get("阵法材料当量"),
                f"品级.{grade_name}.阵法材料当量",
            )
        self._fixed_grades = _texts(
            self._rules.get("固定品级"), "阵法规则.固定品级"
        )
        self._unbounded_grade = _text(
            self._rules.get("无上限品级"), "阵法规则.无上限品级"
        )
        self._fixed_costs = MappingProxyType(self._load_fixed_costs())
        self._town_max_grade_name = _text(
            self._rules.get("城镇最高品级"), "阵法规则.城镇最高品级"
        )
        contract = ContractSet.load(
            self._data.dataset("阵法字段契约").get("阵法字段契约"),
            "物品/规则/阵法/阵法字段契约.json",
        )
        raw_formations = {}
        for formation_id, raw in self._data.entities("阵法").items():
            contract.validate(raw, "阵法", f"阵法 {formation_id}")
            raw_formations[formation_id] = _mapping(raw, f"阵法 {formation_id}")
        self._raw_formations = MappingProxyType(raw_formations)
        self._cost_rules = CraftCostRules(self._data)
        for formation_id, raw in raw_formations.items():
            baseline = _number(
                raw.get("基准当量"), f"阵法 {formation_id}.基准当量"
            )
            if float(baseline) <= 0:
                raise JsonDataError(
                    f"阵法 {formation_id}.基准当量必须大于 0"
                )
        self._formations = MappingProxyType(
            {
                formation_id: FormationDefinition(
                    formation_id,
                    _text(raw.get("名称"), f"阵法 {formation_id}.名称"),
                    _texts(raw.get("宏观监测"), f"阵法 {formation_id}.宏观监测"),
                    _text(raw.get("阵法核心"), f"阵法 {formation_id}.阵法核心"),
                )
                for formation_id, raw in raw_formations.items()
            }
        )
        self._formation_by_name = MappingProxyType(
            {value.name: formation_id for formation_id, value in self._formations.items()}
        )
        if len(self._formation_by_name) != len(self._formations):
            raise JsonDataError("阵法名称不能重复")
        paging = _mapping(
            self._data.dataset("阵法展示").get("阵法-分页"), "阵法展示.阵法-分页"
        )
        self._page_limit = _positive_int(
            _mapping(
                self._data.dataset("阵法规则").get("炼制"), "阵法规则.炼制"
            ).get("每页上限"),
            "阵法.每页上限",
        )
        if _texts(paging.get("品级顺序"), "阵法分页.品级顺序") != _GRADES:
            raise JsonDataError("阵法品级顺序必须为黄品、玄品、地品、天品、圣品")
        self._validate_static_rules()
        self._initialized = True
        return self.status()

    def status(self) -> FormationStatus:
        fixed = self._rules.get("固定品级")
        return FormationStatus(
            self._initialized,
            len(self._formations),
            self._world.facility_count(),
            len(fixed) if isinstance(fixed, Sequence) else 0,
            str(self._rules.get("无上限品级") or ""),
        )

    def formations(self) -> tuple[FormationDefinition, ...]:
        self._require_initialized()
        return tuple(sorted(self._formations.values(), key=lambda value: value.formation_id))

    def formation_name(self, identifier: str) -> str:
        """给升阶方案显示用：按编号或名称取阵法正式名。"""

        self._require_initialized()
        return self._resolve_formation(identifier).name

    def requirements(
        self, identifier: str, grade_name: str, quantity: int = 1
    ) -> tuple[MaterialRequirement, ...]:
        """阵法的两条阵核矿按目标品级固定份数展开；辅材由玩家另行追加。"""

        self._require_initialized()
        count = _positive_int(quantity, "炼阵数量")
        formation = self._resolve_formation(identifier)
        raw = _mapping(
            self._raw_formations.get(formation.formation_id),
            f"阵法 {formation.formation_id}",
        )
        core_ids = tuple(
            _text(value, f"阵法 {formation.formation_id}.阵核[]")
            for value in _sequence(
                raw.get("阵核"), f"阵法 {formation.formation_id}.阵核"
            )
        )
        if len(core_ids) != 2:
            raise JsonDataError(f"阵法阵核必须正好两条：{formation.formation_id}")
        grade = self._asset.grade(grade_name)
        row = self._grade_rows.get(grade.name)
        if row is None:
            raise JsonDataError(f"阵法品级不存在：{grade.name}")
        craft = int(_number(row.get("炼制倍率"), "品级.炼制倍率"))
        return tuple(
            MaterialRequirement("灵矿", core_id, craft * count, grade.grade_id)
            for core_id in core_ids
        )

    def assess(
        self,
        identifier: str,
        grade: str,
        entries: tuple[AssetEntry, ...],
        investments: Mapping[str, int] | None = None,
        facility: CraftFacility | None = None,
    ) -> FormationAssessment:
        self._require_initialized()
        formation = self._resolve_formation(identifier)
        grade_name = _grade_name(grade)
        raw = self._raw_formations[formation.formation_id]
        if "阵核" not in raw or "基础" not in raw:
            raise FormationError(f"阵法缺少阵核或基础：{formation.formation_id}")
        return self._assess_core(formation, raw, grade_name, entries, investments, facility)

    async def overview(self, user_id: str, page: int = 1) -> FormationOverview:
        normalized = _request_text(user_id, "user_id")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise FormationError("页码必须是正整数")
        environment = await self._environment(normalized)
        values = self.formations()
        page_count = max(1, (len(values) + self._page_limit - 1) // self._page_limit)
        if page > page_count:
            raise FormationError(f"页码超出范围：1至{page_count}")
        selected = values[(page - 1) * self._page_limit : page * self._page_limit]
        return FormationOverview(
            normalized,
            environment.location_name,
            environment.facility,
            tuple(FormationEntry(value) for value in selected),
            page,
            page_count,
        )

    async def preview(
        self,
        user_id: str,
        identifier: str,
        grade: str,
        investments: Mapping[str, int] | None = None,
    ) -> FormationPreview:
        normalized = _request_text(user_id, "user_id")
        formation = self._resolve_formation(identifier)
        grade_name = _grade_name(grade)
        environment = await self._environment(normalized)
        entries = await self._material_entries(normalized)
        value = self.assess(
            formation.formation_id,
            grade_name,
            entries,
            investments,
            environment.facility,
        )
        if _grade_order(value.grade_name) > _grade_order(self._town_max_grade_name):
            raise FormationUnavailableError("城镇炼阵最高支持天品")
        request_text = _request_expression(
            value.formation.formation_id,
            _GRADE_IDS[value.grade_name],
            {item.category: item.required for item in value.requirements},
        )
        cost = self._cost_rules.cost("炼阵", value.grade_name) if self._cost_rules else 0
        return FormationPreview(
            normalized,
            environment.location_name,
            environment.facility,
            value.formation,
            value.grade_id,
            value.grade_name,
            request_text,
            value.materials,
            value.requirements,
            value.capacity,
            value.impact,
            value.nodes,
            value.transmission,
            value.can_form and (await self._asset.spirit_stone_balance(normalized)) >= cost,
            value.detection,
            value.core_names,
            value.supplement_multipliers,
            cost,
        )

    async def form(
        self,
        user_id: str,
        request_id: str,
        identifier: str,
        grade: str,
        investments: Mapping[str, int] | None = None,
    ) -> FormationResult:
        normalized = _request_text(user_id, "user_id")
        request = _request_text(request_id, "request_id")
        formation = self._resolve_formation(identifier)
        grade_name = _grade_name(grade)
        committed = await self._database.committed_transaction(normalized, request)
        if committed is not None:
            if (
                committed.receipt.business_type != "炼阵"
                or committed.payload.get("阵法编号") != formation.formation_id
                or committed.payload.get("品级") != grade_name
            ):
                raise FormationConflictError("请求编号已经用于其他操作")
            return self._replayed_result(normalized, formation, committed.payload)
        preview = await self.preview(normalized, formation.formation_id, grade_name, investments)
        if not preview.can_form:
            raise FormationMaterialError("纳戒中的兽宝、灵矿、灵植或灵石不足以炼成该阵法")
        adjustments = tuple(
            InventoryAdjustment(item.item_id, item.grade_id, -item.quantity)
            for item in preview.materials
        )
        actual = {item.category: item.required for item in preview.requirements}
        activation: InnateTreasureActivation | None = None
        modifiers: dict[str, str] = {}
        treasure_effect = await self._innate_treasure.effect(normalized, "阵法成形")
        if treasure_effect is not None:
            treasure, effect = treasure_effect
            if effect.ability == "提高总势":
                ratio = float(effect.values["比例"])
                modifiers = {"总势倍率": str(1.0 + ratio)}
                summary = f"阵法总势提高{ratio:.0%}"
            elif effect.ability == "提高材料阵势":
                material = str(effect.values["材料"])
                ratio = float(effect.values["比例"])
                modifiers = {"材料": material, "材料倍率": str(1.0 + ratio)}
                summary = f"{material}阵势提高{ratio:.0%}"
            else:
                summary = ""
            if summary:
                activation = InnateTreasureActivation(
                    treasure.treasure_id,
                    treasure.name,
                    treasure.authority,
                    summary,
                )
        try:
            inventory = await self._asset.plan_inventory_changes(normalized, adjustments)
            stones = await self._asset.plan_spirit_stone_change(
                normalized, -preview.spirit_stone_cost
            )
            reserve = await self._asset.plan_formation_reserve_acquisition(
                normalized,
                formation.formation_id,
                preview.grade_id,
                materials=(
                    {key: str(actual[key]) for key in _CATEGORIES}
                    if preview.grade_id == "05"
                    else None
                ),
                treasure_id=activation.treasure_id if activation else "",
                modifiers=modifiers,
            )
            payload = {
                "地点": preview.location_name,
                "设施": facility_payload(preview.facility),
                "灵石消耗": preview.spirit_stone_cost,
                "阵法编号": formation.formation_id,
                "品级": preview.grade_name,
                "阵藏条目": reserve.stack.state_key,
                "阵藏原数量": reserve.quantity_before,
                "阵藏现数量": reserve.quantity_after,
                "投入": {key: actual[key] for key in _CATEGORIES},
                "材料": [_material_payload(item) for item in preview.materials],
                "先天灵宝": activation_payload(activation),
                "灵宝效果": modifiers,
            }
            receipt = await self._database.commit(
                TransactionCommand(
                    normalized,
                    request,
                    "炼阵",
                    inventory.operations + stones.operations + (reserve.operation,),
                    payload,
                )
            )
        except StateConflictError as exc:
            raise FormationConflictError("纳戒或阵藏已经变化，请重新审材") from exc
        except IdempotencyConflictError as exc:
            raise FormationConflictError("请求编号已经用于其他操作") from exc
        except (AssetStateError, InventoryChangeError) as exc:
            raise FormationMaterialError(str(exc)) from exc
        return FormationResult(
            preview,
            reserve.stack.state_key,
            reserve.quantity_before,
            reserve.quantity_after,
            receipt.replayed,
            activation,
        )

    async def arm(
        self, user_id: str, request_id: str, identifier: str
    ) -> FormationArmResult:
        normalized = _request_text(user_id, "user_id")
        request = _request_text(request_id, "request_id")
        committed = await self._database.committed_transaction(normalized, request)
        if committed is not None:
            if committed.receipt.business_type != "布阵":
                raise FormationConflictError("请求编号已经用于其他操作")
            return FormationArmResult(
                self._prepared_from_payload(normalized, committed.payload), True
            )
        existing = await self.prepared(normalized)
        reserve_key = await self._resolve_reserve_key(normalized, identifier)
        try:
            reserve = await self._asset.plan_formation_reserve_consumption(
                normalized, reserve_key
            )
            stack = reserve.stack
            # 换阵：旧待战阵法先回阵藏，再扣新阵法；同一件重复布阵直接视为已完成。
            if existing is not None and existing.reserve_key == reserve_key:
                return FormationArmResult(existing, False)
            operations = []
            if existing is not None:
                returned = await self._asset.plan_formation_reserve_acquisition(
                    normalized,
                    existing.formation_id,
                    existing.grade_id,
                    materials=dict(existing.materials),
                    treasure_id=existing.treasure_id,
                    modifiers=dict(existing.modifiers),
                )
                operations.append(returned.operation)
            materials = dict(stack.materials)
            value = {
                "阵藏条目": stack.state_key,
                "阵法编号": stack.formation_id,
                "品级": stack.grade_id,
                "投入": materials,
                "灵宝编号": stack.treasure_id,
                "灵宝效果": dict(stack.modifiers),
            }
            prepared = FormationPrepared(
                normalized,
                stack.state_key,
                stack.formation_id,
                stack.name,
                stack.grade_id,
                _formation_grade_name(stack.grade_id),
                stack.materials,
                stack.treasure_id,
                stack.modifiers,
                1,
                self._treasure_line(stack.treasure_id),
            )
            payload = dict(value)
            payload["名称"] = stack.name
            operations.append(reserve.operation)
            operations.append(
                StateMutation(
                    normalized,
                    _PREPARED_STATE,
                    _PREPARED_KEY,
                    value,
                    existing.version if existing is not None else 0,
                )
            )
            receipt = await self._database.commit(
                TransactionCommand(
                    normalized,
                    request,
                    "布阵",
                    tuple(operations),
                    payload,
                )
            )
        except StateConflictError as exc:
            raise FormationConflictError("阵藏或待战阵法已经变化") from exc
        except IdempotencyConflictError as exc:
            raise FormationConflictError("请求编号已经用于其他操作") from exc
        except AssetStateError as exc:
            raise FormationError(str(exc)) from exc
        return FormationArmResult(prepared, receipt.replayed)

    async def prepared(self, user_id: str) -> FormationPrepared | None:
        self._require_initialized()
        normalized = _request_text(user_id, "user_id")
        snapshot = await self._database.get(
            StateAddress(normalized, _PREPARED_STATE, _PREPARED_KEY)
        )
        if snapshot is None:
            return None
        value = _mapping(snapshot.value, "待战阵法")
        formation_id = _text(value.get("阵法编号"), "待战阵法.阵法编号")
        formation = self._resolve_formation(formation_id)
        grade = self._asset.grade(_text(value.get("品级"), "待战阵法.品级"))
        materials = _stored_materials(value.get("投入"), grade.grade_id)
        treasure_id, modifiers = _stored_treasure_effect(value)
        return FormationPrepared(
            normalized,
            _text(value.get("阵藏条目"), "待战阵法.阵藏条目"),
            formation_id,
            formation.name,
            grade.grade_id,
            _formation_grade_name(grade.grade_id),
            materials,
            treasure_id,
            modifiers,
            snapshot.version,
            self._treasure_line(treasure_id),
        )

    async def snapshot(
        self, user_id: str, *, position: int = 0
    ) -> FormationSnapshot | None:
        """只读的待战快照：切磋用，不产生清除操作。"""

        prepared = await self.prepared(user_id)
        if prepared is None:
            return None
        profile = self.battle_profile(
            prepared.formation_id,
            prepared.grade_name,
            {key: int(value) for key, value in prepared.materials},
            modifiers=dict(prepared.modifiers),
            position=position,
        )
        return FormationSnapshot(prepared, profile)

    async def activation_plan(
        self, user_id: str, *, position: int = 0
    ) -> FormationActivationPlan | None:
        """为下一场正式战斗返回快照，并生成结算时清除待战状态的操作。"""

        snapshot = await self.snapshot(user_id, position=position)
        if snapshot is None:
            return None
        return FormationActivationPlan(
            snapshot.prepared,
            snapshot.profile,
            StateMutation(
                snapshot.prepared.user_id,
                _PREPARED_STATE,
                _PREPARED_KEY,
                None,
                snapshot.prepared.version,
            ),
        )

    def battle_profile(
        self,
        formation_id: str,
        grade: str,
        materials: Mapping[str, int | float] | None = None,
        *,
        modifiers: Mapping[str, str] | None = None,
        position: int = 0,
    ) -> FormationBattleProfile:
        """把稳定阵法引用解析成战斗核心可执行的不可变快照。"""

        self._require_initialized()
        formation = self._resolve_formation(formation_id)
        grade_name = _grade_name(grade)
        raw = self._raw_formations[formation.formation_id]
        if "阵核" not in raw or "基础" not in raw:
            raise FormationError(f"阵法缺少阵核或基础：{formation.formation_id}")
        return self._battle_profile_core(formation, raw, grade_name, materials, position)

    def _material_multipliers(
        self,
        raw: Mapping[str, object],
        grade_name: str,
        totals: Mapping[str, int],
    ) -> dict[str, float]:
        """材料倍率：只按超出固定消耗的部分计，权重取自品级表。"""

        grade_row = self._grade_rows[grade_name]
        unit = float(
            _number(
                grade_row.get("阵法材料当量"),
                f"品级.{grade_name}.阵法材料当量",
            )
        )
        baseline = float(_number(raw.get("基准当量"), "阵法.基准当量"))
        if baseline <= 0:
            raise JsonDataError("阵法.基准当量必须大于 0")
        fixed = self._fixed_costs[grade_name]
        extra = {key: max(0, totals[key] - fixed[key]) for key in _CATEGORIES}
        return {
            key: 1.0 + extra[key] * unit / baseline for key in _CATEGORIES
        }

    def _battle_profile_core(
        self,
        formation: FormationDefinition,
        raw: Mapping[str, object],
        grade_name: str,
        materials: Mapping[str, int | float] | None,
        position: int,
    ) -> FormationBattleProfile:
        grade_row = self._grade_rows[grade_name]
        ability = float(_number(grade_row.get("能力倍率"), "品级.能力倍率"))
        base = _mapping(raw.get("基础"), "阵法.基础")
        actual = {key: 0 for key in _CATEGORIES}
        if materials:
            for key in _CATEGORIES:
                actual[key] = max(0, int(float(materials.get(key, 0))))
        multipliers = self._material_multipliers(raw, grade_name, actual)
        capacity = float(_number(base.get("承载"), "阵法.基础.承载")) * ability * multipliers["灵矿"]
        impact = float(_number(base.get("冲击"), "阵法.基础.冲击")) * ability * multipliers["兽宝"]
        nodes = max(1, int(float(_number(base.get("节点"), "阵法.基础.节点")) * ability * multipliers["灵植"]))
        transmission = float(_number(base.get("传导"), "阵法.基础.传导")) * ability * multipliers["灵植"]
        stages = tuple(
            FormationStageProfile(1.0, 1.0, 1.0) for _ in range(4)
        )
        return FormationBattleProfile(
            formation.formation_id,
            formation.name,
            grade_name,
            int(position),
            capacity,
            impact,
            nodes,
            transmission,
            stages,
            _detection(raw, formation.formation_id),
        )

    def node_rules(self) -> FormationNodeRules:
        """返回战斗核心执行阵法轮转所需的最小不可变契约。"""

        self._require_initialized()
        rules = _mapping(self._rules.get("节点结算"), "阵法规则.节点结算")
        targets = _mapping(rules.get("无敌方阵法"), "阵法规则.无敌方阵法")
        return FormationNodeRules(
            rules.get("敌方阵法优先") is True,
            _text(targets.get("目标数量字段"), "阵法规则.目标数量字段"),
            _texts(targets.get("目标排序"), "阵法规则.目标排序"),
            _text(rules.get("冲击分配"), "阵法规则.冲击分配"),
            rules.get("目标不重复") is True,
            _positive_int(rules.get("最少目标数"), "阵法规则.最少目标数"),
        )

    def _assess_core(
        self,
        formation: FormationDefinition,
        raw: Mapping[str, object],
        grade_name: str,
        entries: tuple[AssetEntry, ...],
        investments: Mapping[str, int] | None,
        facility: CraftFacility | None = None,
    ) -> FormationAssessment:
        """阵核版评估：固定品级按固定消耗，圣品在最低值之上无上限追加。"""

        grade_id = _GRADE_IDS[grade_name]
        grade_row = self._grade_rows[grade_name]
        ability = float(_number(grade_row.get("能力倍率"), "品级.能力倍率"))
        craft = int(_number(grade_row.get("炼制倍率"), "品级.炼制倍率"))
        fixed = self._fixed_costs[grade_name]
        base = _mapping(raw.get("基础"), "阵法.基础")
        core_ids = tuple(
            _text(value, "阵法.阵核[]")
            for value in _sequence(raw.get("阵核"), "阵法.阵核")
        )
        if len(core_ids) != 2:
            raise FormationError("阵法阵核必须正好两条本地灵矿")

        total = dict(fixed)
        if investments:
            unknown = set(investments) - set(_CATEGORIES)
            if unknown:
                raise FormationError(f"阵法辅材未知类别：{sorted(unknown)}")
            values = {}
            for key in _CATEGORIES:
                value = investments.get(key, 0)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise FormationError(f"阵法辅材数量必须是非负整数：{key}")
                values[key] = value
            if grade_name in self._fixed_grades:
                raise FormationError(
                    "黄品、玄品、地品、天品按固定配方炼制，"
                    "不能追加兽宝、灵矿、灵植三数；圣品才可追加"
                )
            short = [key for key in _CATEGORIES if values[key] < fixed[key]]
            if short:
                minimum = "、".join(f"{key}{fixed[key]}" for key in _CATEGORIES)
                raise FormationError(f"圣品三相投入不得低于最低消耗：{minimum}")
            total = values

        requirements = {key: 0 for key in _CATEGORIES}
        remaining = {id(entry): entry.quantity for entry in entries}
        materials: list[FormationMaterial] = []
        selected = {key: 0 for key in _CATEGORIES}

        def take(entry: AssetEntry, quantity: int) -> None:
            nonlocal remaining
            amount = min(quantity, remaining[id(entry)])
            if amount <= 0:
                return
            remaining[id(entry)] -= amount
            selected[entry.subcategory] += amount
            materials.append(
                FormationMaterial(
                    entry.subcategory,
                    entry.content_id,
                    entry.name,
                    entry.grade_id,
                    entry.grade_name,
                    amount,
                )
            )

        core_count = 2 * craft
        paid_total = dict(total)
        if facility is not None:
            for key in _CATEGORIES:
                paid_total[key] = material_quantity(total[key], facility.material_saving_bp)
            paid_total["灵矿"] = max(core_count, paid_total["灵矿"])
        for core_id in core_ids:
            requirements["灵矿"] += craft
            candidates = sorted(
                (
                    entry
                    for entry in entries
                    if entry.subcategory == "灵矿"
                    and entry.content_id == core_id
                    and entry.grade_id == grade_id
                ),
                key=lambda entry: entry.content_id,
            )
            need = craft
            for entry in candidates:
                if need <= 0:
                    break
                before = selected["灵矿"]
                take(entry, need)
                need -= selected["灵矿"] - before

        for category in _CATEGORIES:
            need = paid_total[category] - (core_count if category == "灵矿" else 0)
            if need < 0:
                raise FormationError(f"固定消耗的{category}不足以容纳阵核")
            requirements[category] += need
            candidates = sorted(
                (
                    entry
                    for entry in entries
                    if entry.subcategory == category
                ),
                key=lambda entry: (self._asset.grade(entry.grade_id).order, entry.content_id),
            )
            for entry in candidates:
                if need <= 0:
                    break
                before = selected[category]
                take(entry, need)
                need -= selected[category] - before

        multipliers = self._material_multipliers(raw, grade_name, total)

        capacity = float(_number(base.get("承载"), "阵法.基础.承载")) * ability * multipliers["灵矿"]
        impact = float(_number(base.get("冲击"), "阵法.基础.冲击")) * ability * multipliers["兽宝"]
        nodes = max(1, int(float(_number(base.get("节点"), "阵法.基础.节点")) * ability * multipliers["灵植"]))
        transmission = float(_number(base.get("传导"), "阵法.基础.传导")) * ability * multipliers["灵植"]
        can_form = all(selected[key] >= requirements[key] for key in _CATEGORIES)
        core_names = tuple(
            next(
                (entry.name for entry in entries if entry.content_id == core_id),
                core_id,
            )
            for core_id in core_ids
        )
        return FormationAssessment(
            formation,
            grade_id,
            grade_name,
            tuple(materials),
            tuple(FormationRequirement(key, requirements[key], selected[key]) for key in _CATEGORIES),
            capacity,
            impact,
            nodes,
            transmission,
            can_form,
            _detection(raw, formation.formation_id),
            core_names,
            tuple((key, multipliers[key]) for key in _CATEGORIES),
        )

    async def _material_entries(self, user_id: str) -> tuple[AssetEntry, ...]:
        snapshot = await self._asset.snapshot(user_id)
        return tuple(
            entry
            for entry in snapshot.entries
            if entry.category == "基础物品" and entry.subcategory in _CATEGORIES
        )

    async def _environment(self, user_id: str) -> CraftEnvironment:
        self._require_initialized()
        return await current_environment(
            self._location, self._world, user_id, "炼阵"
        )

    async def _resolve_reserve_key(self, user_id: str, identifier: str) -> str:
        query = _request_text(identifier, "阵藏条目")
        snapshot = await self._asset.snapshot(user_id)
        entries = tuple(entry for entry in snapshot.entries if entry.category == "阵藏")
        # 直中：内部拿的就是条目键（state_key），原样比即可。玩家手打的是中文名/旧写法，走下面的过滤；
        # 扩展位（花括号）只用于存储，不作为输入面。
        direct = next((entry for entry in entries if entry.instance_key == query), None)
        if direct is not None:
            return direct.instance_key
        # 统一语法：品级可并进阵法名（`黄品周天星斗大阵[乾坤鼎]`）——先拆成品级与
        # 灵宝两个独立的槽；旧的「阵法名 品级」与「阵法名[灵宝名]」仍然受理。
        name_part = query
        grade_word = ""
        treasure_word = ""
        try:
            ref = parse_item_ref(query)
        except ItemRefError:
            ref = None
        if ref is not None and (ref.grade or ref.treasure):
            name_part, grade_word, treasure_word = ref.item, ref.grade, ref.treasure
        elif name_part.endswith("]") and "[" in name_part:
            name_part, _, treasure_word = name_part[:-1].partition("[")
            name_part = name_part.strip()
            treasure_word = treasure_word.strip()
        elif " " in query:
            name_part, _, grade_word = query.rpartition(" ")
            name_part = name_part.strip()
            grade_word = grade_word.strip()
        matches = []
        for entry in entries:
            if entry.name != name_part:
                continue
            if grade_word or treasure_word:
                treasure_name = self._treasure_name(getattr(entry, "treasure_id", ""))
                # 品级有短名（黄）与长名（黄品）两种写法，玩家写哪个都认；
                # 比对用双向前缀，免得「黄品」被「黄」挡住。
                if grade_word:
                    grades = {
                        _formation_grade_name(entry.grade_id),
                        str(getattr(entry, "grade_name", "") or ""),
                    }
                    if not any(
                        word and (word.startswith(grade_word) or grade_word.startswith(word))
                        for word in grades
                    ):
                        continue
                if treasure_word and not (
                    treasure_name
                    and (
                        treasure_name.startswith(treasure_word)
                        or treasure_word.startswith(treasure_name)
                    )
                ):
                    continue
            matches.append(entry)
        if not matches:
            raise FormationError("阵藏里没有「" + name_part + "」这座阵法。")
        if len(matches) > 1:
            # 交给命令层铺「选择卡」：显示名带投入（玩家一眼看出差别），中项是**命令尾串**
            # （品级阵法名 + 三个投入数，即规定的旧写法），命令词由各命令自己拼。
            raise FormationChoiceError(
                "阵藏里有多条「" + name_part + "」，请点一条：",
                tuple(
                    _candidate(
                        entry,
                        self._treasure_name(entry.treasure_id)
                        if getattr(entry, "treasure_id", "")
                        else "",
                    )
                    for entry in matches[:4]
                ),
            )
        return matches[0].instance_key

    def _treasure_line(self, treasure_id: str) -> str:
        """待战阵法带先天灵宝时的一句人话：「名字 · 能力摘要」。

        形状来自定义类型的包（`core.innate_treasure.treasure_line`）；没有灵宝就给空串——
        回复那边整段不显示，也不写「无灵宝」三个字。查不到实体就退回编号（与整改前一致）。
        """

        identifier = str(treasure_id or "").strip()
        if not identifier:
            return ""
        try:
            return treasure_line(self._innate_treasure.resolve(identifier))
        except Exception:  # noqa: BLE001 - 展示用；查不到就退回编号
            return identifier

    def _treasure_name(self, treasure_id: str) -> str:
        """先天灵宝的名字（给玩家看的那份）；没有就返回空串。"""
        identifier = str(treasure_id or "").strip()
        if not identifier:
            return ""
        try:
            return self._innate_treasure.resolve(identifier).name
        except Exception:
            return identifier

    def _resolve_formation(self, identifier: str) -> FormationDefinition:
        self._require_initialized()
        query = str(identifier or "").strip()
        value = self._formations.get(query)
        if value is None:
            value = self._formations.get(self._formation_by_name.get(query, ""))
        if value is None:
            raise FormationError(f"未找到唯一阵法：{query or '<空>'}")
        return value

    def _load_fixed_costs(self) -> dict[str, Mapping[str, int]]:
        """黄品基准固定消耗；其余品级按 品级.炼制倍率 放大。"""

        raw = _mapping(self._rules.get("固定消耗"), "阵法规则.固定消耗")
        unknown = set(raw) - set(_CATEGORIES)
        if unknown:
            raise JsonDataError(
                f"阵法固定消耗 有未登记类别：{sorted(unknown)}"
            )
        base = {
            key: nonnegative_int(raw.get(key), f"阵法规则.固定消耗.{key}")
            for key in _CATEGORIES
        }
        result: dict[str, Mapping[str, int]] = {}
        for grade_name in _GRADES:
            craft = int(
                _number(
                    self._grade_rows[grade_name].get("炼制倍率"),
                    "品级.炼制倍率",
                )
            )
            counts = {key: base[key] * craft for key in _CATEGORIES}
            if counts["灵矿"] < 2 * craft:
                raise JsonDataError(
                    f"阵法固定消耗.灵矿 不得少于阵核 {2 * craft} 份"
                )
            result[grade_name] = MappingProxyType(counts)
        return result

    def _validate_static_rules(self) -> None:
        for formation_id, raw in self._raw_formations.items():
            if "阵核" in raw:
                core_ids = _sequence(raw.get("阵核"), f"阵法 {formation_id}.阵核")
                if len(core_ids) != 2:
                    raise JsonDataError(f"阵法阵核必须正好两条：{formation_id}")
                base = _mapping(raw.get("基础"), f"阵法 {formation_id}.基础")
                for key in ("承载", "冲击", "节点", "传导"):
                    _number(base.get(key), f"阵法 {formation_id}.基础.{key}")
                detection = _mapping(raw.get("检测"), f"阵法 {formation_id}.检测")
                if _text(detection.get("字段"), f"阵法 {formation_id}.检测.字段") not in _DETECTION_FIELDS:
                    raise JsonDataError(f"阵法检测字段不是战斗真实字段：{formation_id}")
                description_rule = _mapping(self._rules.get("说明规则"), "阵法规则.说明规则")
                separator = str(description_rule.get("分隔") or "")
                if not separator:
                    raise JsonDataError("说明规则.分隔不能为空")
                paragraphs = str(raw.get("说明") or "").split(separator)
                if len(paragraphs) != int(_number(description_rule.get("段数"), "说明规则.段数")):
                    raise JsonDataError(f"阵法说明必须正好两段：{formation_id}")
                for token in _sequence(description_rule.get("首段关键词"), "说明规则.首段关键词"):
                    if _text(token, "说明规则.首段关键词[]") not in paragraphs[0]:
                        raise JsonDataError(f"阵法说明首段缺少「{token}」：{formation_id}")
                for token in _sequence(description_rule.get("次段关键词"), "说明规则.次段关键词"):
                    if _text(token, "说明规则.次段关键词[]") not in paragraphs[1]:
                        raise JsonDataError(f"阵法说明次段缺少「{token}」：{formation_id}")
                continue
            grades = tuple(
                _text(_mapping(item, "阵法.品级[]").get("品级"), "阵法.品级")
                for item in _sequence(raw.get("品级"), f"阵法 {formation_id}.品级")
            )
            if grades != _GRADES:
                raise JsonDataError(f"阵法五品不完整或顺序错误：{formation_id}")
        if _texts(self._rules.get("固定品级"), "阵法规则.固定品级") != _GRADES[:4]:
            raise JsonDataError("阵法固定品级必须为黄品、玄品、地品、天品")
        if self._rules.get("无上限品级") != "圣品":
            raise JsonDataError("阵法无上限品级必须为圣品")
        if set(self._fixed_grades) | {self._unbounded_grade} != set(_GRADES):
            raise JsonDataError("阵法固定品级与无上限品级必须覆盖五个品级")

    def _replayed_result(
        self,
        user_id: str,
        formation: FormationDefinition,
        payload: Mapping[str, object],
    ) -> FormationResult:
        try:
            location_name = _payload_text(payload.get("地点"), "炼阵事务.地点")
            facility = facility_from_payload(payload.get("设施"), "炼阵事务.设施")
            stone_cost = _payload_nonnegative_int(
                payload.get("灵石消耗"), "炼阵事务.灵石消耗"
            )
            grade_name = _grade_name(_payload_text(payload.get("品级"), "炼阵事务.品级"))
            actual = {
                key: _payload_positive_int(value, f"炼阵事务.投入.{key}")
                for key, value in _mapping(payload.get("投入"), "炼阵事务.投入").items()
            }
            materials = _payload_materials(payload.get("材料"), self._asset, self._data)
            reserve_key = _payload_text(payload.get("阵藏条目"), "炼阵事务.阵藏条目")
            before = _payload_nonnegative_int(payload.get("阵藏原数量"), "炼阵事务.阵藏原数量")
            after = _payload_positive_int(payload.get("阵藏现数量"), "炼阵事务.阵藏现数量")
            activation = _payload_activation(payload.get("先天灵宝"))
            modifiers = {
                str(key): _payload_text(value, f"炼阵事务.灵宝效果.{key}")
                for key, value in _mapping(
                    payload.get("灵宝效果"), "炼阵事务.灵宝效果"
                ).items()
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise FormationConflictError("已提交炼阵事务无法还原") from exc
        profile = self.battle_profile(
            formation.formation_id, grade_name, actual, modifiers=modifiers
        )
        grade = self._asset.grade(_GRADE_IDS[grade_name])
        preview = FormationPreview(
            user_id,
            location_name,
            facility,
            formation,
            grade.grade_id,
            grade_name,
            _request_expression(formation.formation_id, grade.grade_id, actual),
            materials,
            tuple(FormationRequirement(key, actual[key], actual[key]) for key in _CATEGORIES),
            profile.capacity,
            profile.impact,
            profile.nodes,
            profile.transmission,
            True,
            profile.detection,
            (),  # 事务重放只恢复结果，不从阵材反推阵核展示
            (),
            stone_cost,
        )
        return FormationResult(preview, reserve_key, before, after, True, activation)

    def _prepared_from_payload(
        self, user_id: str, payload: Mapping[str, object]
    ) -> FormationPrepared:
        formation_id = _payload_text(payload.get("阵法编号"), "布阵事务.阵法编号")
        formation = self._resolve_formation(formation_id)
        grade = self._asset.grade(_payload_text(payload.get("品级"), "布阵事务.品级"))
        treasure_id, modifiers = _stored_treasure_effect(payload)
        return FormationPrepared(
            user_id,
            _payload_text(payload.get("阵藏条目"), "布阵事务.阵藏条目"),
            formation_id,
            formation.name,
            grade.grade_id,
            _formation_grade_name(grade.grade_id),
            _stored_materials(payload.get("投入"), grade.grade_id),
            treasure_id,
            modifiers,
            1,
            self._treasure_line(treasure_id),
        )

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("阵法核心微服务尚未初始化")


def _materials_hint(entry: object) -> str:
    """候选提示里补出圣品的**投入**，否则「同名字、同品级、同灵宝、投入不同」的几件分不出。

    条目契约只暴露 `material_total`、不暴露投入明细，而明细就写在条目键的扩展位里
    （`05430001{兽宝=1944,灵矿=5832,灵植=3888}`），所以直接从键里截它。
    """

    key = str(getattr(entry, "instance_key", "") or "")
    if "{" not in key or not key.endswith("}"):
        return ""
    return key[key.index("{") :]


def _candidate(entry: object, treasure: str) -> FormationCandidate:
    """把一条阵藏条目做成候选：显示名带投入，两种命令语法各自的尾串都备好。"""

    grade_name = _formation_grade_name(entry.grade_id)
    suffix = ("[" + treasure + "]") if treasure else ""
    return FormationCandidate(
        label=grade_name + entry.name + suffix + _materials_hint(entry),
        tail=grade_name + entry.name + suffix + _materials_tail(entry),
        detail=_materials_hint(entry).strip("{}") or "无投入",
        hall_tail=entry.name + " " + grade_name + _materials_tail(entry),
        key_tail=str(getattr(entry, "instance_key", "") or ""),
    )


def _materials_tail(entry: object) -> str:
    """候选命令的**投入尾串**：按 兽宝 灵矿 灵植 固定顺序给三个数（空格分隔），与手打写法一致。

    条目键里的扩展位已按名称字典序规范化，这里只取三项、按规定顺序排。
    """

    key = str(getattr(entry, "instance_key", "") or "")
    if "{" not in key or not key.endswith("}"):
        return ""
    pairs = dict(
        piece.split("=", 1)
        for piece in key[key.index("{") + 1 : -1].split(",")
        if "=" in piece
    )
    if not all(name in pairs for name in ("兽宝", "灵矿", "灵植")):
        return ""
    return " " + " ".join(pairs[name] for name in ("兽宝", "灵矿", "灵植"))


def _request_expression(formation_id: str, grade_id: str, materials: Mapping[str, object]) -> str:
    """炼阵请求的表达式：**统一形式**（品级＋阵法编号[灵宝]{投入}），与存档键同一套写法。

    以前是「名字 空格 品级」那一套（属第二写法），2026-10-14 收到统一形式；
    圣品的投入进扩展位，于是**请求表达式与阵藏键逐字相同**。
    """

    extra = tuple(
        (str(name), str(amount)) for name, amount in sorted(materials.items())
    )
    return format_item_ref(
        ItemRef(item=formation_id, grade=grade_id, extra=extra if grade_id == "05" else ())
    )


def _material_payload(value: FormationMaterial) -> dict[str, object]:
    return {
        "类别": value.category,
        "编号": value.item_id,
        "品级": value.grade_id,
        "数量": value.quantity,
    }


def _payload_activation(value: object) -> InnateTreasureActivation | None:
    if value is None:
        return None
    raw = _mapping(value, "炼阵事务.先天灵宝")
    return InnateTreasureActivation(
        _payload_text(raw.get("编号"), "炼阵事务.先天灵宝.编号"),
        _payload_text(raw.get("名称"), "炼阵事务.先天灵宝.名称"),
        _payload_text(raw.get("权柄"), "炼阵事务.先天灵宝.权柄"),
        _payload_text(raw.get("结果"), "炼阵事务.先天灵宝.结果"),
    )


def _stored_treasure_effect(
    value: Mapping[str, object],
) -> tuple[str, tuple[tuple[str, str], ...]]:
    treasure_id = str(value.get("灵宝编号") or "").strip()
    modifiers = tuple(
        sorted(
            (
                _payload_text(key, "阵法灵宝效果.字段"),
                _payload_text(raw, f"阵法灵宝效果.{key}"),
            )
            for key, raw in _mapping(
                value.get("灵宝效果"), "阵法灵宝效果"
            ).items()
        )
    )
    if bool(treasure_id) != bool(modifiers):
        raise FormationError("阵法灵宝编号和效果不完整")
    return treasure_id, modifiers


def _payload_materials(
    value: object, asset: AssetService, data: JsonDataService
) -> tuple[FormationMaterial, ...]:
    result: list[FormationMaterial] = []
    for raw in _sequence(value, "炼阵事务.材料"):
        row = _mapping(raw, "炼阵事务.材料[]")
        item_id = _payload_text(row.get("编号"), "炼阵事务.材料.编号")
        grade = asset.grade(_payload_text(row.get("品级"), "炼阵事务.材料.品级"))
        result.append(
            FormationMaterial(
                _payload_text(row.get("类别"), "炼阵事务.材料.类别"),
                item_id,
                _text(data.entity("基础物品", item_id).get("名称"), f"物品 {item_id}.名称"),
                grade.grade_id,
                grade.name,
                _payload_positive_int(row.get("数量"), "炼阵事务.材料.数量"),
            )
        )
    return tuple(result)


def _stored_materials(value: object, grade_id: str) -> tuple[tuple[str, str], ...]:
    if grade_id != "05":
        return ()
    raw = _mapping(value, "待战阵法.投入")
    if set(raw) != set(_CATEGORIES):
        raise FormationError("圣品待战阵法投入不完整")
    return tuple(
        (key, _decimal_text(raw.get(key), f"待战阵法.投入.{key}"))
        for key in _CATEGORIES
    )


def _decimal_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    try:
        decimal = Decimal(text)
    except InvalidOperation as exc:
        raise FormationError(f"{label}必须是十进制数") from exc
    if not decimal.is_finite() or decimal <= 0:
        raise FormationError(f"{label}必须大于0")
    return format(decimal, "f")


def _grade_name(value: object) -> str:
    """品级名一律以**全名**为准（黄品…）；旧数据/旧调用里的短名（黄…）一并受理。"""

    text = str(value or "").strip()
    if text in _GRADES:
        return text
    full = text + "品"
    if full in _GRADES:
        return full
    raise FormationError(f"阵法品级必须是{'、'.join(_GRADES)}")


def _grade_order(value: str) -> int:
    # 与 _grade_name 同一口径：以全名为准，旧短名一并受理。
    text = str(value or "").strip()
    key = text if text in _GRADES else text + "品"
    try:
        return _GRADES.index(key)
    except ValueError as exc:
        raise JsonDataError(f"未知阵法品级：{value}") from exc


def _formation_grade_name(grade_id: str) -> str:
    try:
        return _GRADE_NAMES_BY_ID[grade_id]
    except KeyError as exc:
        raise FormationError(f"未知阵法品级编号：{grade_id}") from exc


def _texts(value: object, label: str) -> tuple[str, ...]:
    return tuple(_text(item, label) for item in _sequence(value, label))




def _request_text(value: object, label: str) -> str:
    return nonempty_text(value, label, error=FormationError)


def _payload_text(value: object, label: str) -> str:
    return strict_text(value, label, error=ValueError)


def _payload_positive_int(value: object, label: str) -> int:
    return positive_int(value, label, error=ValueError)


def _payload_nonnegative_int(value: object, label: str) -> int:
    return nonnegative_int(value, label, error=ValueError)


__all__ = ["FormationService"]
