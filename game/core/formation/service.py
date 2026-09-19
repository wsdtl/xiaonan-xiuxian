"""解释阵法 JSON，并管理炼阵、待战与战斗快照。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
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
    positive_int,
    positive_int as _positive_int,
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
)
from game.core.location import LocationService
from game.core.world import LocationQuery, WorldService
from game.core.world import WORLD_CONTRACT_DATASET, WORLD_CONTRACT_PATH

from .contracts import (
    FormationActivationPlan,
    FormationArmResult,
    FormationAssessment,
    FormationBattleProfile,
    FormationConflictError,
    FormationDefinition,
    FormationEntry,
    FormationError,
    FormationMaster,
    FormationMaterial,
    FormationMaterialError,
    FormationNodeRules,
    FormationOverview,
    FormationPrepared,
    FormationPreview,
    FormationRequirement,
    FormationResult,
    FormationStageProfile,
    FormationStatus,
    FormationUnavailableError,
)
from game.core.data import (
    number as _number,
    sequence as _sequence,
    strict_text,
    strict_text as _text,
)

_CATEGORIES = ("兽宝", "灵矿", "灵植")
_GRADES = ("黄", "玄", "地", "天", "圣")
_GRADE_IDS = dict(zip(_GRADES, ("01", "02", "03", "04", "05"), strict=True))
_GRADE_NAMES_BY_ID = {grade_id: name for name, grade_id in _GRADE_IDS.items()}
_PREPARED_STATE = "prepared_formation"
_PREPARED_KEY = "main"


class FormationService:
    """阵法定义、材料投入、阵藏转换和战斗快照的唯一入口。"""

    state_types = frozenset({_PREPARED_STATE})

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
        self._raw_formations: Mapping[str, Mapping[str, object]] = MappingProxyType({})
        self._formations: Mapping[str, FormationDefinition] = MappingProxyType({})
        self._formation_by_name: Mapping[str, str] = MappingProxyType({})
        self._masters: Mapping[str, FormationMaster] = MappingProxyType({})
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
        self._town_max_grade_name = _text(
            self._rules.get("城镇最高品级"), "阵法规则.城镇最高品级"
        )
        contract = ContractSet.load(
            self._data.dataset("阵法字段契约").get("阵法字段契约"),
            "物品/阵法/规则/阵法字段契约.json",
        )
        raw_formations = {}
        for formation_id, raw in self._data.entities("阵法").items():
            contract.validate(raw, "阵法", f"阵法 {formation_id}")
            raw_formations[formation_id] = _mapping(raw, f"阵法 {formation_id}")
        self._raw_formations = MappingProxyType(raw_formations)
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
        self._masters = MappingProxyType(self._load_masters())
        paging = _mapping(
            self._data.dataset("阵法展示").get("分页"), "阵法展示.分页"
        )
        self._page_limit = _positive_int(paging.get("每页上限"), "阵法分页.每页上限")
        if _texts(paging.get("品级顺序"), "阵法分页.品级顺序") != _GRADES:
            raise JsonDataError("阵法品级顺序必须为黄、玄、地、天、圣")
        self._validate_static_rules()
        self._initialized = True
        return self.status()

    def status(self) -> FormationStatus:
        fixed = self._rules.get("固定品级")
        return FormationStatus(
            self._initialized,
            len(self._formations),
            len(self._masters),
            len(fixed) if isinstance(fixed, Sequence) else 0,
            str(self._rules.get("无上限品级") or ""),
        )

    def formations(self, master_location: str = "") -> tuple[FormationDefinition, ...]:
        self._require_initialized()
        if master_location:
            master = next(
                (value for value in self._masters.values() if value.location_name == master_location),
                None,
            )
            if master is None:
                raise FormationUnavailableError("此地没有能够主持炼阵的阵师")
            return tuple(self._formations[item] for item in master.formation_ids)
        return tuple(sorted(self._formations.values(), key=lambda value: value.formation_id))

    def assess(
        self,
        identifier: str,
        grade: str,
        entries: tuple[AssetEntry, ...],
        investments: Mapping[str, int] | None = None,
    ) -> FormationAssessment:
        self._require_initialized()
        formation = self._resolve_formation(identifier)
        grade_name = _grade_name(grade)
        required = self._required_materials(formation.formation_id, grade_name, investments)
        materials, requirements = self._select_materials(entries, required)
        profile = self.battle_profile(
            formation.formation_id,
            grade_name,
            {item.category: item.required for item in requirements},
        )
        grade_value = self._asset.grade(_GRADE_IDS[grade_name])
        return FormationAssessment(
            formation,
            grade_value.grade_id,
            grade_name,
            materials,
            requirements,
            profile.capacity,
            profile.impact,
            profile.nodes,
            profile.transmission,
            all(not item.missing for item in requirements),
        )

    async def overview(self, user_id: str, page: int = 1) -> FormationOverview:
        normalized = _request_text(user_id, "user_id")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise FormationError("页码必须是正整数")
        location_name, master = await self._current_master(normalized)
        values = tuple(self._formations[item] for item in master.formation_ids)
        page_count = max(1, (len(values) + self._page_limit - 1) // self._page_limit)
        if page > page_count:
            raise FormationError(f"页码超出范围：1至{page_count}")
        selected = values[(page - 1) * self._page_limit : page * self._page_limit]
        return FormationOverview(
            normalized,
            location_name,
            master,
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
        location_name, master = await self._current_master(normalized)
        if formation.formation_id not in master.formation_ids:
            raise FormationUnavailableError("这座阵台没有开放该阵法")
        entries = await self._material_entries(normalized)
        value = self.assess(formation.formation_id, grade_name, entries, investments)
        if _grade_order(value.grade_name) > _grade_order(self._town_max_grade_name):
            raise FormationUnavailableError("城镇炼阵最高支持天品")
        request_text = _request_expression(
            value.formation.name,
            value.grade_name,
            {item.category: item.required for item in value.requirements},
        )
        return FormationPreview(
            normalized,
            location_name,
            master,
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
            value.can_form,
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
            raise FormationMaterialError("纳戒中的兽宝、灵矿和灵植不足以炼成该阵法")
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
                "阵师编号": preview.master.master_id,
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
                    inventory.operations + (reserve.operation,),
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
        if existing is not None:
            raise FormationConflictError("已有一座阵法处于待战状态")
        reserve_key = await self._resolve_reserve_key(normalized, identifier)
        try:
            reserve = await self._asset.plan_formation_reserve_consumption(
                normalized, reserve_key
            )
            stack = reserve.stack
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
            )
            payload = dict(value)
            payload["名称"] = stack.name
            receipt = await self._database.commit(
                TransactionCommand(
                    normalized,
                    request,
                    "布阵",
                    (
                        reserve.operation,
                        StateMutation(
                            normalized,
                            _PREPARED_STATE,
                            _PREPARED_KEY,
                            value,
                            0,
                        ),
                    ),
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
        )

    async def activation_plan(
        self, user_id: str, *, position: int = 0
    ) -> FormationActivationPlan | None:
        """为下一场正式战斗返回快照，并生成结算时清除待战状态的操作。"""

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
        return FormationActivationPlan(
            prepared,
            profile,
            StateMutation(
                prepared.user_id,
                _PREPARED_STATE,
                _PREPARED_KEY,
                None,
                prepared.version,
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
        grade_raw = self._grade_raw(raw, grade_name)
        effect_values = {str(key): str(value) for key, value in (modifiers or {}).items()}
        unknown_effects = set(effect_values) - {"总势倍率", "材料", "材料倍率"}
        if unknown_effects:
            raise FormationError(f"阵法灵宝效果包含未知字段：{sorted(unknown_effects)}")
        if grade_name == "圣":
            minimum = {
                str(key): float(value)
                for key, value in _mapping(grade_raw.get("最低消耗"), "圣品.最低消耗").items()
            }
            actual = {str(key): float(value) for key, value in (materials or {}).items()}
            unknown = set(actual) - set(_CATEGORIES)
            if unknown or any(actual.get(key, 0) < minimum[key] for key in _CATEGORIES):
                raise FormationError("圣品阵法材料投入不完整或低于最低消耗")
            if "材料" in effect_values:
                material = effect_values["材料"]
                if material not in _CATEGORIES or "材料倍率" not in effect_values:
                    raise FormationError("阵法材料灵宝效果不完整")
                actual[material] *= float(effect_values["材料倍率"])
            growth = _mapping(self._rules.get("圣品增长"), "阵法规则.圣品增长")
            weights = {
                str(key): float(value)
                for key, value in _mapping(grade_raw.get("圣品权重"), "圣品.权重").items()
            }
            total = 1.0
            for direction in _sequence(growth.get("方向"), "圣品增长.方向"):
                value = _mapping(direction, "圣品增长.方向[]")
                material = _text(value.get("材料"), "圣品增长.材料")
                part = _text(value.get("部位"), "圣品增长.部位")
                total *= (actual[material] / minimum[material]) ** weights[part]
            derived: dict[str, float] = {}
            for direction in _sequence(growth.get("方向"), "圣品增长.方向"):
                value = _mapping(direction, "圣品增长.方向[]")
                part = _text(value.get("部位"), "圣品增长.部位")
                section = _mapping(grade_raw.get(part), f"圣品.{part}")
                for output in _sequence(value.get("结果"), "圣品增长.结果"):
                    output_value = _mapping(output, "圣品增长.结果[]")
                    result = float(section[_text(output_value.get("基础值"), "基础值")]) * total
                    if output_value.get("取整") == "向下取整":
                        result = float(math.floor(result))
                    if "最小值" in output_value:
                        result = max(float(output_value["最小值"]), result)
                    derived[_text(output_value.get("运行值"), "运行值")] = result
            capacity = derived["承载"]
            impact = derived["冲击"]
            nodes = int(derived["数量"])
            transmission = derived["传导"]
        else:
            base = _mapping(grade_raw.get("阵基"), "阵法.阵基")
            eye = _mapping(grade_raw.get("阵眼"), "阵法.阵眼")
            nodes_raw = _mapping(grade_raw.get("节点"), "阵法.节点")
            capacity = _number(base.get("承载"), "阵法.承载")
            impact = _number(eye.get("冲击"), "阵法.冲击")
            nodes = _positive_int(nodes_raw.get("数量"), "阵法.节点数量")
            transmission = _number(nodes_raw.get("传导"), "阵法.传导")
            if "材料" in effect_values:
                material = effect_values["材料"]
                multiplier = float(effect_values.get("材料倍率", "0"))
                if material == "灵矿":
                    capacity *= multiplier
                elif material == "兽宝":
                    impact *= multiplier
                elif material == "灵植":
                    nodes = max(1, math.ceil(nodes * multiplier))
                    transmission *= multiplier
                else:
                    raise FormationError("阵法材料灵宝效果引用未知材料")
        if "总势倍率" in effect_values:
            multiplier = float(effect_values["总势倍率"])
            if multiplier <= 0:
                raise FormationError("阵法总势倍率必须为正数")
            capacity *= multiplier
            impact *= multiplier
            nodes = max(1, math.ceil(nodes * multiplier))
            transmission *= multiplier
        stages = tuple(
            FormationStageProfile(
                _number(value.get("环境阶段阈值倍率"), "阵法.环境阶段阈值倍率"),
                _number(value.get("行动周期倍率"), "阵法.行动周期倍率"),
                _number(value.get("阵势倍率"), "阵法.阵势倍率"),
            )
            for value in (
                _mapping(raw_stage, "阵法.地势阶段[]")
                for raw_stage in _sequence(grade_raw.get("地势阶段"), "阵法.地势阶段")
            )
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

    def _required_materials(
        self,
        formation_id: str,
        grade_name: str,
        investments: Mapping[str, int] | None,
    ) -> dict[str, int]:
        raw = self._grade_raw(self._raw_formations[formation_id], grade_name)
        if grade_name != "圣":
            if investments:
                raise FormationError("天地玄黄阵法使用固定投入，不能追加材料")
            source = _mapping(raw.get("消耗"), "阵法.消耗")
            return {key: _positive_int(source.get(key), f"阵法.消耗.{key}") for key in _CATEGORIES}
        minimum = _mapping(raw.get("最低消耗"), "圣品阵法.最低消耗")
        result = {
            key: _positive_int(minimum.get(key), f"圣品阵法.最低消耗.{key}")
            for key in _CATEGORIES
        }
        if investments is None:
            return result
        if set(investments) != set(_CATEGORIES):
            raise FormationError("圣品投入必须同时给出兽宝、灵矿和灵植数量")
        for key in _CATEGORIES:
            value = investments[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < result[key]:
                raise FormationError(f"圣品{key}投入不能低于{result[key]}")
            result[key] = value
        return result

    def _select_materials(
        self, entries: tuple[AssetEntry, ...], required: Mapping[str, int]
    ) -> tuple[tuple[FormationMaterial, ...], tuple[FormationRequirement, ...]]:
        materials: list[FormationMaterial] = []
        requirements: list[FormationRequirement] = []
        for category in _CATEGORIES:
            remaining = required[category]
            selected = 0
            candidates = sorted(
                (entry for entry in entries if entry.subcategory == category),
                key=lambda entry: (
                    self._asset.grade(entry.grade_id).order,
                    entry.content_id,
                ),
            )
            for entry in candidates:
                if remaining <= 0:
                    break
                quantity = min(remaining, entry.quantity)
                materials.append(
                    FormationMaterial(
                        category,
                        entry.content_id,
                        entry.name,
                        entry.grade_id,
                        entry.grade_name,
                        quantity,
                    )
                )
                selected += quantity
                remaining -= quantity
            requirements.append(FormationRequirement(category, required[category], selected))
        return tuple(materials), tuple(requirements)

    async def _material_entries(self, user_id: str) -> tuple[AssetEntry, ...]:
        snapshot = await self._asset.snapshot(user_id)
        return tuple(
            entry
            for entry in snapshot.entries
            if entry.category == "基础物品" and entry.subcategory in _CATEGORIES
        )

    async def _current_master(self, user_id: str) -> tuple[str, FormationMaster]:
        self._require_initialized()
        current = await self._location.current(user_id)
        place = self._world.locate(LocationQuery(xy=current.xy))
        if not place.location_name or "炼阵" not in place.available_functions:
            raise FormationUnavailableError("此地没有能够主持炼阵的阵师")
        master = self._masters.get(place.location_name)
        if master is None:
            raise FormationUnavailableError("此地没有能够主持炼阵的阵师")
        return place.location_name, master

    async def _resolve_reserve_key(self, user_id: str, identifier: str) -> str:
        query = _request_text(identifier, "阵藏条目")
        snapshot = await self._asset.snapshot(user_id)
        entries = tuple(entry for entry in snapshot.entries if entry.category == "阵藏")
        direct = next((entry for entry in entries if entry.instance_key == query), None)
        if direct is not None:
            return direct.instance_key
        parts = query.rsplit(" ", 1)
        matches = [
            entry
            for entry in entries
            if entry.name == parts[0]
            and (
                len(parts) == 1
                or _formation_grade_name(entry.grade_id) == _grade_name(parts[1])
            )
        ]
        if len(matches) != 1:
            raise FormationError("未找到唯一阵藏条目，请使用阵藏条目编号")
        return matches[0].instance_key

    def _resolve_formation(self, identifier: str) -> FormationDefinition:
        self._require_initialized()
        query = str(identifier or "").strip()
        value = self._formations.get(query)
        if value is None:
            value = self._formations.get(self._formation_by_name.get(query, ""))
        if value is None:
            raise FormationError(f"未找到唯一阵法：{query or '<空>'}")
        return value

    def _grade_raw(
        self, raw: Mapping[str, object], grade_name: str
    ) -> Mapping[str, object]:
        grades = {
            _text(value.get("品级"), "阵法.品级"): value
            for value in (
                _mapping(item, "阵法.品级[]")
                for item in _sequence(raw.get("品级"), "阵法.品级")
            )
        }
        try:
            return grades[grade_name]
        except KeyError as exc:
            raise FormationError(f"阵法没有{grade_name}品配置") from exc

    def _load_masters(self) -> dict[str, FormationMaster]:
        result: dict[str, FormationMaster] = {}
        contract = ContractSet.from_dataset(
            self._data.dataset(WORLD_CONTRACT_DATASET), WORLD_CONTRACT_PATH
        )
        for master_id, raw in self._data.entities("阵师").items():
            contract.validate(raw, "阵师", f"阵师 {master_id}")
            location = self._data.entity_record("阵师", master_id).directory_owner
            if not location:
                raise JsonDataError(f"阵师 {master_id} 缺少地点目录归属")
            if location in result:
                raise JsonDataError(f"同一地点不能有多名主持阵师：{location}")
            formation_ids = _texts(raw.get("开放阵法"), f"阵师 {master_id}.开放阵法")
            if len(formation_ids) != len(set(formation_ids)):
                raise JsonDataError(f"阵师开放阵法重复：{master_id}")
            unknown = set(formation_ids) - set(self._formations)
            if unknown:
                raise JsonDataError(f"阵师引用未知阵法：{sorted(unknown)}")
            result[location] = FormationMaster(
                master_id,
                _text(raw.get("名称"), f"阵师 {master_id}.名称"),
                location,
                _text(raw.get("称号"), f"阵师 {master_id}.称号"),
                _text(raw.get("阵台"), f"阵师 {master_id}.阵台"),
                _text(raw.get("阵道传承"), f"阵师 {master_id}.阵道传承"),
                _text(raw.get("话语风格"), f"阵师 {master_id}.话语风格"),
                _speech(raw.get("话语"), f"阵师 {master_id}.话语"),
                formation_ids,
            )
        return result

    def _validate_static_rules(self) -> None:
        if len(self._formations) != 46:
            raise JsonDataError("当前阵法必须完整定义46座")
        locations = {
            item.name
            for item in self._world.map_view().locations
            if "炼阵" in item.available_functions
        }
        if set(self._masters) != locations:
            raise JsonDataError(
                f"炼阵地点与阵师不一一对应：缺少{sorted(locations - set(self._masters))}，"
                f"多余{sorted(set(self._masters) - locations)}"
            )
        opened = [item for master in self._masters.values() for item in master.formation_ids]
        if len(opened) != len(set(opened)) or set(opened) != set(self._formations):
            raise JsonDataError("46座阵法必须各由一个地点独占开放")
        for formation_id, raw in self._raw_formations.items():
            grades = tuple(
                _text(_mapping(item, "阵法.品级[]").get("品级"), "阵法.品级")
                for item in _sequence(raw.get("品级"), f"阵法 {formation_id}.品级")
            )
            if grades != _GRADES:
                raise JsonDataError(f"阵法五品不完整或顺序错误：{formation_id}")
        if _texts(self._rules.get("固定品级"), "阵法规则.固定品级") != _GRADES[:4]:
            raise JsonDataError("阵法固定品级必须为黄、玄、地、天")
        if self._rules.get("无上限品级") != "圣":
            raise JsonDataError("阵法无上限品级必须为圣")

    def _replayed_result(
        self,
        user_id: str,
        formation: FormationDefinition,
        payload: Mapping[str, object],
    ) -> FormationResult:
        try:
            location_name = _payload_text(payload.get("地点"), "炼阵事务.地点")
            master = self._masters[location_name]
            if master.master_id != _payload_text(payload.get("阵师编号"), "炼阵事务.阵师编号"):
                raise ValueError("炼阵事务阵师与地点不一致")
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
            master,
            formation,
            grade.grade_id,
            grade_name,
            _request_expression(formation.name, grade_name, actual),
            materials,
            tuple(FormationRequirement(key, actual[key], actual[key]) for key in _CATEGORIES),
            profile.capacity,
            profile.impact,
            profile.nodes,
            profile.transmission,
            True,
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
        )

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("阵法核心微服务尚未初始化")


def _request_expression(name: str, grade: str, materials: Mapping[str, int]) -> str:
    base = f"{name} {grade}"
    if grade != "圣":
        return base
    return f"{base} {materials['兽宝']} {materials['灵矿']} {materials['灵植']}"


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
    result = str(value or "").strip().removesuffix("品")
    if result not in _GRADES:
        raise FormationError(f"阵法品级必须是{'、'.join(_GRADES)}")
    return result


def _grade_order(value: str) -> int:
    try:
        return _GRADES.index(value)
    except ValueError as exc:
        raise JsonDataError(f"未知阵法品级：{value}") from exc


def _formation_grade_name(grade_id: str) -> str:
    try:
        return _GRADE_NAMES_BY_ID[grade_id]
    except KeyError as exc:
        raise FormationError(f"未知阵法品级编号：{grade_id}") from exc


def _texts(value: object, label: str) -> tuple[str, ...]:
    return tuple(_text(item, label) for item in _sequence(value, label))


def _speech(value: object, label: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    expected = {"总览", "审材", "齐备", "不足", "完成"}
    if set(value) != expected:
        raise JsonDataError(f"{label}必须完整包含：{'、'.join(sorted(expected))}")
    return MappingProxyType({key: _text(value[key], f"{label}.{key}") for key in expected})


def _request_text(value: object, label: str) -> str:
    return nonempty_text(value, label, error=FormationError)


def _payload_text(value: object, label: str) -> str:
    return strict_text(value, label, error=ValueError)


def _payload_positive_int(value: object, label: str) -> int:
    return positive_int(value, label, error=ValueError)


def _payload_nonnegative_int(value: object, label: str) -> int:
    return nonnegative_int(value, label, error=ValueError)


__all__ = ["FormationService"]
