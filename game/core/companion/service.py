"""解释世界道侣定义并管理玩家关系、同行位与轻实例。"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from types import MappingProxyType

from game.core.combat import CombatantSpec, CombatBuildRef, generate_five_elements
from game.core.data import (
    ContractSet,
    JsonDataError,
    JsonDataService,
    mapping,
    mapping as _mapping,
    nonnegative_int,
    nonnegative_int as _nonnegative_int,
    positive_int,
    positive_int as _positive_int,
)
from game.core.database import DatabaseService, StateAddress, StateMutation
from game.core.forging import ForgingService
from game.core.growth import GrowthService
from game.core.medicine import PreparedBattleMedicine
from game.core.world import WORLD_CONTRACT_DATASET, WORLD_CONTRACT_PATH

from .contracts import (
    ActiveCompanion,
    ActiveCompanionInstance,
    CompanionBattleMedicinePlan,
    CompanionBattlePlan,
    CompanionBreakthroughCorrectionPlan,
    CompanionBreakthroughPlan,
    CompanionBuildResetPlan,
    CompanionCultivationError,
    CompanionCultivationResetPlan,
    CompanionDefinition,
    CompanionDialogue,
    CompanionFarewellError,
    CompanionFarewellPlan,
    CompanionGiftError,
    CompanionGiftPlan,
    CompanionGrowthPlan,
    CompanionInstance,
    CompanionInvitationError,
    CompanionInvitationPlan,
    CompanionLawPlan,
    CompanionMedicineSettingPlan,
    CompanionNotFoundError,
    CompanionRecoveryPlan,
    CompanionRelation,
    CompanionRetreatPlan,
    CompanionReward,
    CompanionRules,
    CompanionSeverancePlan,
    CompanionStateError,
    CompanionStatus,
    LocalCultivator,
)

RELATION_STATE = "companion_relation"
ACTIVE_STATE = "companion_active"
INSTANCE_STATE = "companion_instance"
ACTIVE_KEY = "main"
_AFFECTION_QUANTUM = Decimal("0.1")


class CompanionService:
    """拥有道侣静态身份和玩家个人道侣状态的核心边界。"""

    state_types = frozenset({RELATION_STATE, ACTIVE_STATE, INSTANCE_STATE})

    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService,
        growth: GrowthService,
        forging: ForgingService,
    ) -> None:
        self._data = data
        self._database = database
        self._growth = growth
        self._forging = forging
        self._initialized = False
        self._rules: CompanionRules | None = None
        self._definitions: Mapping[str, CompanionDefinition] = MappingProxyType({})
        self._by_name: Mapping[str, str] = MappingProxyType({})
        self._by_location: Mapping[str, tuple[LocalCultivator, ...]] = MappingProxyType(
            {}
        )
        self._attribute_definitions: Mapping[str, object] = {}
        self._plant_pool_meridians: Mapping[str, str] = {}
        self._five_element_rules: Mapping[str, object] = {}

    def initialize(self) -> CompanionStatus:
        if self._initialized:
            raise RuntimeError("道侣核心微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据服务必须先于道侣核心启动")
        if not self._database.status().initialized:
            raise RuntimeError("核心数据库必须先于道侣核心启动")
        if not self._growth.status().initialized:
            raise RuntimeError("成长核心必须先于道侣核心启动")
        if not self._forging.status().initialized:
            raise RuntimeError("炼器核心必须先于道侣核心启动")
        self._five_element_rules = _mapping(
            self._data.dataset("战斗规则").get("五行"), "战斗/规则/五行.json"
        )
        self._rules = self._load_rules()
        self._attribute_definitions = _mapping(
            self._data.dataset("战斗定义").get("属性"), "战斗定义.属性"
        )
        self._plant_pool_meridians = self._load_plant_pool_meridians()
        if (
            self._rules.qualification_growth_minimum <= 0
            or self._rules.qualification_growth_maximum
            < self._rules.qualification_growth_minimum
        ):
            raise JsonDataError("道侣资质成长倍率必须为正数且最高倍率不低于最低倍率")
        if self._rules.active_limit != 1:
            raise JsonDataError("当前同行位契约要求道侣.同行上限为1")
        if self._rules.full_reward_lifetime_limit != 1:
            raise JsonDataError("当前回礼契约要求每名道侣终身次数为1")
        realms = self._realms()
        grade_ids = frozenset(
            _text(value.get("编号"), "品级.编号")
            for value in _sequence(
                self._data.dataset("基础定义").get("品级"), "基础/定义/品级.json"
            )
        )
        definitions: dict[str, CompanionDefinition] = {}
        by_name: dict[str, str] = {}
        by_location: dict[str, list[LocalCultivator]] = {}
        contract = ContractSet.from_dataset(
            self._data.dataset(WORLD_CONTRACT_DATASET), WORLD_CONTRACT_PATH
        )
        for companion_id, value in self._data.entities("道侣").items():
            contract.validate(value, "道侣", f"道侣 {companion_id}")
            definition = self._definition(companion_id, value, realms, grade_ids)
            normalized_name = _normalize(definition.name)
            if normalized_name in by_name:
                raise JsonDataError(f"道侣名称重复：{definition.name}")
            definitions[companion_id] = definition
            by_name[normalized_name] = companion_id
            by_location.setdefault(definition.location_name, []).append(
                LocalCultivator(
                    definition.companion_id,
                    definition.name,
                    definition.gender,
                    definition.title,
                    definition.description,
                    definition.realm_id,
                    definition.realm_name,
                    definition.level,
                    definition.interactable,
                )
            )
        self._definitions = MappingProxyType(definitions)
        self._by_name = MappingProxyType(by_name)
        self._by_location = MappingProxyType(
            {
                location: tuple(
                    sorted(values, key=lambda item: (item.name, item.companion_id))
                )
                for location, values in by_location.items()
            }
        )
        self._initialized = True
        return self.status()

    def status(self) -> CompanionStatus:
        return CompanionStatus(
            self._initialized,
            len(self._definitions),
            len(self._by_location),
        )

    def rules(self) -> CompanionRules:
        self._require_initialized()
        if self._rules is None:
            raise CompanionStateError("道侣规则尚未完成初始化")
        return self._rules

    def definition(self, identifier: str) -> CompanionDefinition:
        self._require_initialized()
        query = str(identifier or "").strip()
        companion_id = (
            query
            if query in self._definitions
            else self._by_name.get(_normalize(query))
        )
        if companion_id is None:
            raise CompanionNotFoundError(f"未找到道侣：{query or '<空>'}")
        return self._definitions[companion_id]

    def gift_preference(self, companion_id: str, item_id: str) -> str:
        """返回赠礼在该道侣定义中的正式喜好层级。"""

        definition = self.definition(companion_id)
        normalized = str(item_id or "").strip()
        if normalized in definition.favorite_item_ids:
            return "偏爱"
        if normalized in definition.acceptable_item_ids:
            return "合意"
        return "拒绝"

    def local_cultivators(
        self,
        location_name: str,
        *,
        exclude_companion_ids: Sequence[str] = (),
    ) -> tuple[LocalCultivator, ...]:
        self._require_initialized()
        normalized = str(location_name or "").strip()
        if not normalized:
            return ()
        excluded = frozenset(
            str(value or "").strip() for value in exclude_companion_ids
        )
        return tuple(
            value
            for value in self._by_location.get(normalized, ())
            if value.companion_id not in excluded
        )

    async def relation(self, user_id: str, companion_id: str) -> CompanionRelation:
        self._require_initialized()
        definition = self.definition(companion_id)
        snapshot = await self._database.get(
            StateAddress(_user_id(user_id), RELATION_STATE, definition.companion_id)
        )
        if snapshot is None:
            return CompanionRelation(
                definition.companion_id,
                Decimal(0),
                MappingProxyType({}),
                "",
                "",
                0,
            )
        value = _state_mapping(snapshot.value, f"{RELATION_STATE}/{companion_id}")
        allowed = {"当前好感", "赠礼累计", "首次圆满时间", "首次邀约时间"}
        if unknown := set(value) - allowed:
            raise CompanionStateError(
                f"道侣关系包含未知字段：{'、'.join(sorted(unknown))}"
            )
        totals_value = _state_mapping(value.get("赠礼累计"), "道侣关系.赠礼累计")
        totals: dict[str, int] = {}
        for key, raw in totals_value.items():
            parts = str(key).split(":")
            if len(parts) != 2 or len(parts[0]) != 6 or len(parts[1]) != 2:
                raise CompanionStateError(f"赠礼累计键无效：{key}")
            totals[str(key)] = _state_positive_int(raw, f"赠礼累计.{key}")
        return CompanionRelation(
            definition.companion_id,
            _state_affection(value.get("当前好感"), "道侣关系.当前好感"),
            MappingProxyType(dict(sorted(totals.items()))),
            _optional_text(value.get("首次圆满时间")),
            _optional_text(value.get("首次邀约时间")),
            snapshot.version,
        )

    async def active(self, user_id: str) -> ActiveCompanion | None:
        self._require_initialized()
        snapshot = await self._database.get(
            StateAddress(_user_id(user_id), ACTIVE_STATE, ACTIVE_KEY)
        )
        if snapshot is None:
            return None
        value = _state_mapping(snapshot.value, f"{ACTIVE_STATE}/{ACTIVE_KEY}")
        if set(value) != {"道侣编号"}:
            raise CompanionStateError("同行道侣状态必须只保存道侣编号")
        companion_id = _state_text(value.get("道侣编号"), "同行道侣.道侣编号")
        self.definition(companion_id)
        return ActiveCompanion(companion_id, snapshot.version)

    async def instance(
        self, user_id: str, companion_id: str
    ) -> CompanionInstance | None:
        self._require_initialized()
        definition = self.definition(companion_id)
        snapshot = await self._database.get(
            StateAddress(_user_id(user_id), INSTANCE_STATE, definition.companion_id)
        )
        if snapshot is None:
            return None
        value = _state_mapping(snapshot.value, f"{INSTANCE_STATE}/{companion_id}")
        expected = {
            "境界",
            "等级",
            "经验",
            "属性",
            "修行槽",
            "本命武器",
            "资质",
            "属性倍率",
            "突破记录",
            "资源",
            "自动用药",
            "待战战丹",
            "五行根性",
        }
        if set(value) != expected:
            raise CompanionStateError("道侣实例字段不完整")
        multipliers_value = _state_mapping(value.get("属性倍率"), "道侣实例.属性倍率")
        if set(multipliers_value) != set(definition.fluctuating_attributes):
            raise CompanionStateError("道侣实例属性倍率与正式定义不一致")
        multipliers = {
            str(key): _state_positive_int(raw, f"道侣实例.属性倍率.{key}")
            for key, raw in multipliers_value.items()
        }
        realm_id = _state_text(value.get("境界"), "道侣实例.境界")
        self._growth.realm(realm_id)
        attributes_value = _state_mapping(value.get("属性"), "道侣实例.属性")
        attributes = {
            str(key): _state_number(raw, f"道侣实例.属性.{key}")
            for key, raw in attributes_value.items()
        }
        five_elements = _state_five_elements(value.get("五行根性"))
        resources_value = _state_mapping(value.get("资源"), "道侣实例.资源")
        resources = {
            name: _state_number(resources_value.get(name), f"道侣实例.资源.{name}")
            for name in ("血气", "精神")
        }
        cultivation_value = _state_mapping(value.get("修行槽"), "道侣实例.修行槽")
        cultivation = {
            category: tuple(
                _state_text(raw, f"道侣实例.修行槽.{category}[]")
                for raw in _state_sequence(
                    cultivation_value.get(category),
                    f"道侣实例.修行槽.{category}",
                )
            )
            for category in ("功法", "真意", "气机")
        }
        for category, content_ids in cultivation.items():
            for content_id in content_ids:
                self._data.entity(category, content_id)
        weapon = _state_mapping(value.get("本命武器"), "道侣实例.本命武器")
        weapon_laws = tuple(
            None if raw is None else _state_text(raw, "道侣实例.本命武器.器律[]")
            for raw in _state_sequence(
                weapon.get("器律"), "道侣实例.本命武器.器律", allow_empty=True
            )
        )
        for law_id in weapon_laws:
            if law_id is not None:
                self._data.entity("器律", law_id)
        weapon_level = _state_positive_int(weapon.get("等级"), "道侣实例.本命武器.等级")
        stage = self._forging.weapon_stage(weapon_level)
        stage_name, open_slots = stage.name, stage.open_law_slots
        if _state_text(weapon.get("器阶"), "道侣实例.本命武器.器阶") != stage_name:
            raise CompanionStateError("道侣本命武器器阶与等级不一致")
        if len(weapon_laws) > open_slots:
            raise CompanionStateError("道侣本命武器器律超过已开放孔位")
        return CompanionInstance(
            definition.companion_id,
            realm_id,
            _state_positive_int(value.get("等级"), "道侣实例.等级"),
            _state_nonnegative_int(value.get("经验"), "道侣实例.经验"),
            MappingProxyType(attributes),
            MappingProxyType(cultivation),
            _state_text(weapon.get("名称"), "道侣实例.本命武器.名称"),
            weapon_level,
            _state_nonnegative_int(weapon.get("经验"), "道侣实例.本命武器.经验"),
            weapon_laws,
            _state_positive_int(value.get("资质"), "道侣实例.资质"),
            MappingProxyType(multipliers),
            tuple(
                _state_mapping(raw, "道侣实例.突破记录[]")
                for raw in _state_sequence(
                    value.get("突破记录"),
                    "道侣实例.突破记录",
                    allow_empty=True,
                )
            ),
            snapshot.version,
            MappingProxyType(resources),
            _state_bool(value.get("自动用药"), "道侣实例.自动用药"),
            _prepared_battle_medicine(value.get("待战战丹"), "道侣实例.待战战丹"),
            MappingProxyType(five_elements),
        )

    async def active_instance(self, user_id: str) -> ActiveCompanionInstance:
        """取得当前同行事实及其唯一培养实例。"""

        active = await self.active(user_id)
        if active is None:
            raise CompanionCultivationError("当前没有同行道侣")
        instance = await self.instance(user_id, active.companion_id)
        if instance is None:
            raise CompanionStateError("当前同行道侣缺少培养实例")
        return ActiveCompanionInstance(active, instance)

    async def combatant(self, user_id: str) -> CombatantSpec | None:
        """返回当前同行道侣的战斗快照；没有同行道侣时返回空。"""

        active = await self.active(user_id)
        if active is None:
            return None
        instance = await self.instance(user_id, active.companion_id)
        if instance is None:
            raise CompanionStateError("当前同行道侣缺少培养实例")
        definition = self.definition(instance.companion_id)
        build = tuple(
            CombatBuildRef(
                section=category,
                content_id=content_id,
                instance_id=f"{user_id}:{instance.companion_id}:{category}:{index}",
                born_order=index,
            )
            for category, content_ids in instance.cultivation.items()
            for index, content_id in enumerate(content_ids, start=1)
        ) + tuple(
            CombatBuildRef(
                section="器律",
                content_id=content_id,
                instance_id=f"{user_id}:{instance.companion_id}:器律:{index}",
                born_order=index,
            )
            for index, content_id in enumerate(instance.weapon_laws, start=1)
            if content_id
        )
        return CombatantSpec(
            id=f"companion:{user_id}:{instance.companion_id}",
            name=definition.name,
            attributes=instance.attributes,
            level=instance.level,
            combatant_type="修士",
            weapon_attack=self._forging.weapon_attack(instance.weapon_level),
            build=build,
            health=float(instance.resources["血气"]),
            spirit=float(instance.resources["精神"]),
            auto_medicine=instance.automatic_medicine,
            owner_id=user_id,
            controller_id=user_id,
            inventory_owner_id=user_id,
            gender=definition.gender,
            five_elements=dict(instance.five_elements),
        )

    async def plan_growth(
        self,
        user_id: str,
        *,
        experience: int = 0,
        weapon_experience: int = 0,
    ) -> CompanionGrowthPlan:
        """只为当前同行道侣结算人物与本命武器成长。"""

        current = await self.active_instance(user_id)
        before = current.instance
        try:
            cultivator = self._growth.advance_cultivator(
                level=before.level,
                experience=before.experience,
                realm_id=before.realm_id,
                gained=_request_nonnegative_int(experience, "道侣经验"),
            )
            weapon = self._forging.advance_weapon(
                level=before.weapon_level,
                experience=before.weapon_experience,
                gained=_request_nonnegative_int(weapon_experience, "道侣本命武器经验"),
            )
        except ValueError as exc:
            raise CompanionCultivationError(str(exc)) from exc
        definition = self.definition(before.companion_id)
        multiplier = _qualification_multiplier(before, definition, self.rules())
        attributes = _add_numbers(
            before.attributes,
            self._growth.cultivator_attribute_growth(
                cultivator.levels_gained,
                multiplier=multiplier,
            ),
        )
        after = CompanionInstance(
            before.companion_id,
            before.realm_id,
            cultivator.level_after,
            cultivator.experience_after,
            MappingProxyType(attributes),
            before.cultivation,
            before.weapon_name,
            weapon.level_after,
            weapon.experience_after,
            before.weapon_laws,
            before.qualification,
            before.attribute_multipliers,
            before.breakthrough_records,
            before.version + 1,
            before.resources,
            before.automatic_medicine,
            before.prepared_battle_medicine,
            before.five_elements,
        )
        return CompanionGrowthPlan(
            before.companion_id,
            before.level,
            after.level,
            before.weapon_level,
            after.weapon_level,
            self._active_instance_operations(user_id, current, after),
        )

    async def plan_breakthrough(
        self, user_id: str, *, medicine_id: str
    ) -> CompanionBreakthroughPlan:
        """只为当前同行道侣生成独立突破。"""

        current = await self.active_instance(user_id)
        before = current.instance
        realm = self._growth.realm(before.realm_id)
        if before.level != realm.maximum_level:
            raise CompanionCultivationError(
                f"{self.definition(before.companion_id).name}达到"
                f"{realm.maximum_level}级后才能突破{realm.name}"
            )
        next_realm = self._growth.next_realm(before.realm_id)
        medicine, permanent = self._breakthrough_medicine(
            medicine_id, next_realm.realm_id
        )
        if any(
            record.get("目标境界") == next_realm.realm_id
            for record in before.breakthrough_records
        ):
            raise CompanionCultivationError("该道侣已经完成此次境界突破")
        definition = self.definition(before.companion_id)
        multiplier = _qualification_multiplier(before, definition, self.rules())
        advance = self._growth.advance_cultivator(
            level=before.level,
            experience=before.experience,
            realm_id=next_realm.realm_id,
            gained=0,
        )
        attributes = _add_numbers(before.attributes, permanent)
        attributes = _add_numbers(
            attributes,
            self._growth.cultivator_attribute_growth(
                advance.levels_gained,
                multiplier=multiplier,
            ),
        )
        records = before.breakthrough_records + (
            MappingProxyType(
                {
                    "目标境界": next_realm.realm_id,
                    "突破丹": str(medicine.get("编号")),
                    "补正来源丹药": None,
                }
            ),
        )
        after = CompanionInstance(
            before.companion_id,
            next_realm.realm_id,
            advance.level_after,
            advance.experience_after,
            MappingProxyType(attributes),
            before.cultivation,
            before.weapon_name,
            before.weapon_level,
            before.weapon_experience,
            before.weapon_laws,
            before.qualification,
            before.attribute_multipliers,
            records,
            before.version + 1,
            before.resources,
            before.automatic_medicine,
            before.prepared_battle_medicine,
            before.five_elements,
        )
        return CompanionBreakthroughPlan(
            before.companion_id,
            before.realm_id,
            next_realm.realm_id,
            next_realm.name,
            str(medicine.get("编号")),
            self._active_instance_operations(user_id, current, after),
        )

    async def plan_weapon_law(
        self, user_id: str, *, law_id: str, slot: int
    ) -> CompanionLawPlan:
        """只覆炼当前同行道侣自己的本命武器。"""

        if isinstance(slot, bool) or not isinstance(slot, int) or slot < 1:
            raise CompanionCultivationError("器律孔位必须是正整数")
        current = await self.active_instance(user_id)
        before = current.instance
        law = self._data.entity("器律", str(law_id or "").strip())
        law_name = _text(law.get("名称"), "器律.名称")
        law_stage = _text(law.get("器阶"), "器律.器阶")
        open_slots = self._forging.weapon_stage(before.weapon_level).open_law_slots
        if slot > open_slots:
            raise CompanionCultivationError(
                f"当前道侣本命武器只开放{open_slots}个器律孔"
            )
        if not self._forging.law_allowed(before.weapon_level, law_stage):
            raise CompanionCultivationError("该器律的器阶高于道侣本命武器")
        laws = list(before.weapon_laws)
        laws.extend([None] * (slot - len(laws)))
        replaced = laws[slot - 1]
        normalized_law_id = _text(law.get("编号") or law_id, "器律.编号")
        laws[slot - 1] = normalized_law_id
        after = CompanionInstance(
            before.companion_id,
            before.realm_id,
            before.level,
            before.experience,
            before.attributes,
            before.cultivation,
            before.weapon_name,
            before.weapon_level,
            before.weapon_experience,
            tuple(laws),
            before.qualification,
            before.attribute_multipliers,
            before.breakthrough_records,
            before.version + 1,
            before.resources,
            before.automatic_medicine,
            before.prepared_battle_medicine,
            before.five_elements,
        )
        return CompanionLawPlan(
            before.companion_id,
            slot,
            normalized_law_id,
            law_name,
            "" if replaced is None else replaced,
            self._active_instance_operations(user_id, current, after),
        )

    def _active_instance_operations(
        self,
        user_id: str,
        current: ActiveCompanionInstance,
        after: CompanionInstance,
    ) -> tuple[StateMutation, ...]:
        normalized_user_id = _user_id(user_id)
        return (
            StateMutation(
                normalized_user_id,
                INSTANCE_STATE,
                after.companion_id,
                _instance_value(after, self._forging),
                current.instance.version,
            ),
            StateMutation(
                normalized_user_id,
                ACTIVE_STATE,
                ACTIVE_KEY,
                {"道侣编号": current.active.companion_id},
                current.active.version,
            ),
        )

    async def plan_medicine_setting(
        self, user_id: str, *, enabled: bool
    ) -> CompanionMedicineSettingPlan:
        """生成当前同行道侣的自动用药开关变更。"""

        if not isinstance(enabled, bool):
            raise CompanionCultivationError("自动用药开关必须是布尔值")
        current = await self.active_instance(user_id)
        before = current.instance
        if before.automatic_medicine == enabled:
            raise CompanionCultivationError(
                f"道侣自动用药已经{'开启' if enabled else '关闭'}"
            )
        after = replace(before, automatic_medicine=enabled, version=before.version + 1)
        return CompanionMedicineSettingPlan(
            before.companion_id,
            enabled,
            self._active_instance_operations(user_id, current, after),
        )

    async def plan_recovery(
        self, user_id: str, *, resource: str, recovery_percent: float
    ) -> CompanionRecoveryPlan:
        """按当前同行道侣的资源上限生成一次主动恢复。"""

        current = await self.active_instance(user_id)
        before = current.instance
        normalized_resource = _medicine_resource(resource)
        percent = _positive_number(recovery_percent, "恢复百分比")
        maximum = _number(
            before.attributes.get(f"{normalized_resource}上限"),
            f"道侣{normalized_resource}上限",
        )
        current_value = _bounded_resource(
            before.resources.get(normalized_resource),
            maximum,
            f"道侣当前{normalized_resource}",
        )
        if current_value >= maximum:
            raise CompanionCultivationError(f"道侣{normalized_resource}已满")
        after_value = min(maximum, current_value + maximum * percent / 100)
        resources = dict(before.resources)
        resources[normalized_resource] = _clean_number(after_value)
        after = replace(
            before,
            resources=MappingProxyType(resources),
            version=before.version + 1,
        )
        return CompanionRecoveryPlan(
            before.companion_id,
            normalized_resource,
            current_value,
            after_value,
            after_value - current_value,
            self._active_instance_operations(user_id, current, after),
        )

    async def plan_battle_medicine(
        self,
        user_id: str,
        *,
        medicine: PreparedBattleMedicine | None,
        require_empty: bool = False,
    ) -> CompanionBattleMedicinePlan:
        """寄存或清除当前同行道侣下一场正式战斗使用的战丹。"""

        current = await self.active_instance(user_id)
        before = current.instance
        if require_empty and before.prepared_battle_medicine is not None:
            raise CompanionCultivationError("当前同行道侣已有待战战丹")
        if before.prepared_battle_medicine == medicine:
            raise CompanionCultivationError("道侣待战战丹没有变化")
        after = replace(
            before,
            prepared_battle_medicine=medicine,
            version=before.version + 1,
        )
        return CompanionBattleMedicinePlan(
            before.companion_id,
            before.prepared_battle_medicine,
            medicine,
            self._active_instance_operations(user_id, current, after),
        )

    async def plan_battle_settlement(
        self,
        user_id: str,
        *,
        health: float,
        spirit: float,
        weapon_experience: int = 0,
    ) -> CompanionBattlePlan:
        """只结算当前同行道侣的战后资源与本命武器经验。"""

        current = await self.active_instance(user_id)
        before = current.instance
        gained = _request_nonnegative_int(weapon_experience, "道侣本命武器经验")
        advance = self._forging.advance_weapon(
            level=before.weapon_level,
            experience=before.weapon_experience,
            gained=gained,
        )
        health_after = _bounded_resource(
            health, before.attributes.get("血气上限"), "道侣战后血气"
        )
        spirit_after = _bounded_resource(
            spirit, before.attributes.get("精神上限"), "道侣战后精神"
        )
        after = replace(
            before,
            weapon_level=advance.level_after,
            weapon_experience=advance.experience_after,
            resources=MappingProxyType({"血气": health_after, "精神": spirit_after}),
            version=before.version + 1,
        )
        return CompanionBattlePlan(
            before.companion_id,
            health_after,
            spirit_after,
            gained,
            StateMutation(
                _user_id(user_id),
                INSTANCE_STATE,
                before.companion_id,
                _instance_value(after, self._forging),
                before.version,
            ),
        )

    async def plan_retreat_settlement(
        self,
        user_id: str,
        *,
        companion_id: str,
        experience: int,
        health_recovery_ratio: float,
        spirit_recovery_ratio: float,
    ) -> CompanionRetreatPlan:
        """为开始时锁定的同行道侣合并闭关经验与恢复。"""

        current = await self.active_instance(user_id)
        before = current.instance
        expected_id = _text(companion_id, "闭关道侣编号")
        if before.companion_id != expected_id:
            raise CompanionCultivationError("同行道侣已经发生变化")
        gained = _request_nonnegative_int(experience, "闭关道侣经验")
        health_ratio = _request_ratio(health_recovery_ratio, "闭关血气恢复比例")
        spirit_ratio = _request_ratio(spirit_recovery_ratio, "闭关精神恢复比例")
        try:
            advance = self._growth.advance_cultivator(
                level=before.level,
                experience=before.experience,
                realm_id=before.realm_id,
                gained=gained,
            )
        except ValueError as exc:
            raise CompanionCultivationError(str(exc)) from exc
        definition = self.definition(before.companion_id)
        multiplier = _qualification_multiplier(before, definition, self.rules())
        attributes = _add_numbers(
            before.attributes,
            self._growth.cultivator_attribute_growth(
                advance.levels_gained,
                multiplier=multiplier,
            ),
        )
        health_maximum = _state_number(attributes.get("血气上限"), "道侣.血气上限")
        spirit_maximum = _state_number(attributes.get("精神上限"), "道侣.精神上限")
        health = _bounded_resource(
            _state_number(before.resources.get("血气"), "道侣.血气")
            + health_maximum * health_ratio,
            health_maximum,
            "闭关后道侣血气",
        )
        spirit = _bounded_resource(
            _state_number(before.resources.get("精神"), "道侣.精神")
            + spirit_maximum * spirit_ratio,
            spirit_maximum,
            "闭关后道侣精神",
        )
        after = replace(
            before,
            level=advance.level_after,
            experience=advance.experience_after,
            attributes=MappingProxyType(attributes),
            resources=MappingProxyType({"血气": health, "精神": spirit}),
            version=before.version + 1,
        )
        return CompanionRetreatPlan(
            before.companion_id,
            gained,
            advance.level_before,
            advance.level_after,
            health,
            spirit,
            StateMutation(
                _user_id(user_id),
                INSTANCE_STATE,
                before.companion_id,
                _instance_value(after, self._forging),
                before.version,
            ),
        )

    async def plan_cultivation_reset(
        self, user_id: str
    ) -> CompanionCultivationResetPlan:
        """把当前同行道侣的等级与突破所得全部退回初始状态。"""

        current = await self.active_instance(user_id)
        before = current.instance
        definition = self.definition(before.companion_id)
        initial_realm = self._growth.realm_for_level(1)
        attributes = self._initial_attributes(
            definition,
            before.qualification,
            before.attribute_multipliers,
        )
        resources = {
            resource: _bounded_resource(
                before.resources.get(resource),
                attributes.get(f"{resource}上限"),
                f"夺元后道侣{resource}",
            )
            for resource in ("血气", "精神")
        }
        after = replace(
            before,
            realm_id=initial_realm.realm_id,
            level=1,
            experience=0,
            attributes=MappingProxyType(attributes),
            breakthrough_records=(),
            resources=MappingProxyType(resources),
            version=before.version + 1,
        )
        user = _user_id(user_id)
        return CompanionCultivationResetPlan(
            before.companion_id,
            before.realm_id,
            initial_realm.realm_id,
            initial_realm.name,
            before.level,
            1,
            StateMutation(
                user,
                INSTANCE_STATE,
                before.companion_id,
                _instance_value(after, self._forging),
                before.version,
            ),
            StateMutation(
                user,
                ACTIVE_STATE,
                ACTIVE_KEY,
                {"道侣编号": before.companion_id},
                current.active.version,
            ),
        )

    async def plan_build_reset(
        self, user_id: str, *, category: str
    ) -> CompanionBuildResetPlan:
        """只重抽当前同行道侣的一类构筑，器律永远不在此范围。"""

        current = await self.active_instance(user_id)
        before = current.instance
        normalized = str(category or "").strip()
        if normalized not in {"功法", "真意", "气机"}:
            raise CompanionCultivationError("道侣归元只能选择功法、真意或气机")
        definition = self.definition(before.companion_id)
        build = self._growth.redraw_companion_category(
            pools=definition.cultivation_pools,
            current=before.cultivation,
            category=normalized,
            slots=self.rules().cultivation_slots,
        )
        cultivation = dict(before.cultivation)
        cultivation[normalized] = build.content_ids
        after = replace(
            before,
            cultivation=MappingProxyType(cultivation),
            version=before.version + 1,
        )
        return CompanionBuildResetPlan(
            before.companion_id,
            normalized,
            build.content_ids,
            self._active_instance_operations(user_id, current, after),
        )

    async def plan_breakthrough_correction(
        self, user_id: str, *, source_medicine_id: str
    ) -> CompanionBreakthroughCorrectionPlan:
        """为当前同行道侣的纯突破节点写入一项永久属性。"""

        current = await self.active_instance(user_id)
        before = current.instance
        records = [dict(row) for row in before.breakthrough_records]
        record = next((row for row in records if row.get("目标境界") == before.realm_id), None)
        if record is None:
            raise CompanionCultivationError("当前境界没有可补正的突破节点")
        if record.get("补正来源丹药"):
            raise CompanionCultivationError("当前突破节点已经补正")
        _, original_permanent = self._breakthrough_medicine(
            _text(record.get("突破丹"), "突破记录.突破丹"), before.realm_id
        )
        if original_permanent:
            raise CompanionCultivationError("只有纯突破节点可以补正")
        _, permanent = self._breakthrough_medicine(source_medicine_id, before.realm_id)
        if len(permanent) != 1:
            raise CompanionCultivationError("补正丹必须只提供一项永久属性")
        attributes = _add_numbers(before.attributes, permanent)
        record["补正来源丹药"] = str(source_medicine_id).strip()
        records[records.index(record)] = record
        after = replace(
            before,
            attributes=MappingProxyType(attributes),
            breakthrough_records=tuple(MappingProxyType(item) for item in records),
            version=before.version + 1,
        )
        return CompanionBreakthroughCorrectionPlan(
            before.companion_id,
            before.realm_id,
            str(source_medicine_id).strip(),
            tuple((str(key), value) for key, value in permanent.items()),
            self._active_instance_operations(user_id, current, after),
        )

    async def plan_severance(self, user_id: str) -> CompanionSeverancePlan:
        """归零当前同行道侣好感并解除同行，保留全部历史事实。"""

        current = await self.active_instance(user_id)
        relation = await self.relation(user_id, current.instance.companion_id)
        after = CompanionRelation(
            relation.companion_id,
            Decimal(0),
            relation.gift_totals,
            relation.first_full_at,
            relation.first_invited_at,
            relation.version + 1,
        )
        user = _user_id(user_id)
        return CompanionSeverancePlan(
            relation.companion_id,
            relation.current_affection,
            (
                StateMutation(
                    user,
                    RELATION_STATE,
                    relation.companion_id,
                    _relation_value(after),
                    relation.version,
                ),
                StateMutation(
                    user,
                    ACTIVE_STATE,
                    ACTIVE_KEY,
                    None,
                    current.active.version,
                ),
            ),
        )

    def _breakthrough_medicine(
        self, medicine_id: str, target_realm_id: str
    ) -> tuple[Mapping[str, object], Mapping[str, int | float]]:
        normalized = str(medicine_id or "").strip()
        medicine = self._data.entity("丹药", normalized)
        if self._data.entity_record("丹药", normalized).number_category != "丹药":
            raise CompanionCultivationError("只能使用突破丹突破境界")
        effect = _mapping(medicine.get("使用效果"), "突破丹.使用效果")
        if (
            effect.get("类型") != "境界突破"
            or effect.get("目标境界") != target_realm_id
        ):
            raise CompanionCultivationError("该突破丹不对应道侣的下一境界")
        permanent = _mapping(effect.get("永久属性", {}), "突破丹.永久属性")
        return medicine, {
            str(name): _number(raw, f"突破丹.永久属性.{name}")
            for name, raw in permanent.items()
        }

    async def plan_gift(
        self,
        user_id: str,
        companion_id: str,
        *,
        item_id: str,
        grade_id: str,
        quantity: int,
        affection_gain: Decimal,
        occurred_at: str,
    ) -> CompanionGiftPlan:
        definition = self.definition(companion_id)
        normalized_item_id = str(item_id or "").strip()
        if self.gift_preference(definition.companion_id, normalized_item_id) == "拒绝":
            raise CompanionGiftError(f"{definition.name}不愿收下这件物品")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise CompanionGiftError("赠礼数量必须是正整数")
        gain = _positive_affection(affection_gain, "赠礼好感")
        relation = await self.relation(user_id, definition.companion_id)
        after_affection = _quantize(relation.current_affection + gain)
        normalized_grade_id = str(grade_id or "").strip()
        if len(normalized_grade_id) != 2 or not normalized_grade_id.isdecimal():
            raise CompanionGiftError("赠礼品级编号无效")
        gift_key = f"{normalized_item_id}:{normalized_grade_id}"
        totals = dict(relation.gift_totals)
        totals[gift_key] = totals.get(gift_key, 0) + quantity
        first_full = (
            not relation.first_full_at
            and after_affection >= self.rules().full_reward_affection
        )
        first_full_at = occurred_at if first_full else relation.first_full_at
        after = CompanionRelation(
            definition.companion_id,
            after_affection,
            MappingProxyType(dict(sorted(totals.items()))),
            first_full_at,
            relation.first_invited_at,
            relation.version + 1,
        )
        return CompanionGiftPlan(
            relation,
            after,
            first_full,
            StateMutation(
                _user_id(user_id),
                RELATION_STATE,
                definition.companion_id,
                _relation_value(after),
                relation.version,
            ),
        )

    async def plan_invitation(
        self,
        user_id: str,
        companion_id: str,
        *,
        player_gender: str,
        occurred_at: str,
        random_source: random.Random | None = None,
    ) -> CompanionInvitationPlan:
        definition = self.definition(companion_id)
        relation = await self.relation(user_id, definition.companion_id)
        if relation.current_affection < self.rules().invitation_affection:
            raise CompanionInvitationError(
                f"当前好感为{_display_affection(relation.current_affection)}，"
                f"达到{_display_affection(self.rules().invitation_affection)}后才能邀约"
            )
        active = await self.active(user_id)
        instance = await self.instance(user_id, definition.companion_id)
        if active is not None:
            if active.companion_id == definition.companion_id:
                if instance is None:
                    raise CompanionStateError("同行道侣缺少轻实例")
                return CompanionInvitationPlan(relation, instance, False, True, ())
            active_name = self.definition(active.companion_id).name
            raise CompanionInvitationError(f"{active_name}正在与你同行，请先暂别")
        first_invitation = not relation.first_invited_at
        if (
            (first_invitation or self.rules().check_gender_again)
            and self.rules().first_invitation_gender_relation == "不同"
            and str(player_gender or "").strip() == definition.gender
        ):
            reason = "首次邀约" if first_invitation else "再次邀约"
            raise CompanionInvitationError(f"{reason}要求双方性别不同")
        if first_invitation:
            if instance is not None:
                raise CompanionStateError("未曾邀约的道侣已经存在轻实例")
            instance = self._new_instance(definition, random_source)
        elif instance is None:
            raise CompanionStateError("曾经邀约的道侣缺少轻实例")

        operations: list[StateMutation] = []
        if first_invitation:
            relation = CompanionRelation(
                relation.companion_id,
                relation.current_affection,
                relation.gift_totals,
                relation.first_full_at,
                occurred_at,
                relation.version + 1,
            )
            operations.append(
                StateMutation(
                    _user_id(user_id),
                    RELATION_STATE,
                    definition.companion_id,
                    _relation_value(relation),
                    relation.version - 1,
                )
            )
            operations.append(
                StateMutation(
                    _user_id(user_id),
                    INSTANCE_STATE,
                    definition.companion_id,
                    _instance_value(instance, self._forging),
                    0,
                )
            )
        operations.append(
            StateMutation(
                _user_id(user_id),
                ACTIVE_STATE,
                ACTIVE_KEY,
                {"道侣编号": definition.companion_id},
                0,
            )
        )
        return CompanionInvitationPlan(
            relation,
            instance,
            first_invitation,
            False,
            tuple(operations),
        )

    async def plan_farewell(
        self, user_id: str, companion_id: str
    ) -> CompanionFarewellPlan:
        definition = self.definition(companion_id)
        active = await self.active(user_id)
        if active is None:
            raise CompanionFarewellError("当前没有同行道侣")
        if active.companion_id != definition.companion_id:
            active_name = self.definition(active.companion_id).name
            raise CompanionFarewellError(f"当前与你同行的是{active_name}")
        return CompanionFarewellPlan(
            definition.companion_id,
            StateMutation(
                _user_id(user_id),
                ACTIVE_STATE,
                ACTIVE_KEY,
                None,
                active.version,
            ),
        )

    def _new_instance(
        self,
        definition: CompanionDefinition,
        random_source: random.Random | None,
    ) -> CompanionInstance:
        source = random_source or random.SystemRandom()
        qualification = source.randint(*definition.qualification_range)
        multipliers = {
            attribute: source.randint(*definition.attribute_multiplier_range)
            for attribute in definition.fluctuating_attributes
        }
        attributes = self._initial_attributes(definition, qualification, multipliers)
        attributes = _add_numbers(
            attributes,
            self._growth.cultivator_attribute_growth(
                max(0, definition.level - 1),
                multiplier=_qualification_multiplier_value(
                    qualification, definition, self.rules()
                ),
            ),
        )
        build = self._growth.random_companion_build(
            pools=definition.cultivation_pools,
            slots=self.rules().cultivation_slots,
            seed=source.getrandbits(64),
        )
        return CompanionInstance(
            definition.companion_id,
            definition.realm_id,
            definition.level,
            0,
            MappingProxyType(attributes),
            MappingProxyType(
                {
                    "功法": build.techniques,
                    "真意": build.intents,
                    "气机": build.qi_patterns,
                }
            ),
            definition.weapon_name,
            definition.weapon_level,
            definition.weapon_experience,
            definition.weapon_laws,
            qualification,
            MappingProxyType(multipliers),
            (),
            1,
            MappingProxyType(
                {
                    "血气": attributes["血气上限"],
                    "精神": attributes["精神上限"],
                }
            ),
            self.rules().automatic_medicine_default,
            None,
            MappingProxyType(generate_five_elements(self._five_element_rules, source)),
        )

    def _initial_attributes(
        self,
        definition: CompanionDefinition,
        qualification: int,
        multipliers: Mapping[str, int],
    ) -> dict[str, int | float]:
        minimum, maximum = definition.qualification_range
        if not minimum <= qualification <= maximum:
            raise CompanionStateError("道侣资质超出正式定义范围")
        if set(multipliers) != set(definition.fluctuating_attributes):
            raise CompanionStateError("道侣属性倍率与正式定义不一致")
        overrides = {
            name: _scaled_number(raw, multipliers.get(name, 100))
            for name, raw in definition.attribute_overrides.items()
        }
        attributes = {
            name: _number(_mapping(raw, f"属性.{name}").get("默认值"), name)
            for name, raw in self._attribute_definitions.items()
        }
        attributes.update(overrides)
        return attributes

    def _load_rules(self) -> CompanionRules:
        value = _mapping(
            self._data.dataset("角色规则").get("道侣"),
            "角色/规则/主体/道侣.json",
        )
        invitation = _mapping(value.get("邀约"), "道侣.邀约")
        gift_rules = _mapping(value.get("赠礼喜好"), "道侣.赠礼喜好")
        acceptable_rule = _mapping(
            gift_rules.get("合意推导"), "道侣.赠礼喜好.合意推导"
        )
        if acceptable_rule != {
            "来源": "炼药规则.归脉",
            "条件": "与偏爱灵植池本脉相同",
        }:
            raise JsonDataError("道侣合意灵植必须按炼药归脉的同本脉关系推导")
        if gift_rules.get("拒绝倍率") != 0:
            raise JsonDataError("道侣拒绝赠礼倍率必须为0")
        reward = _mapping(value.get("圆满回礼"), "道侣.圆满回礼")
        slots_value = _mapping(value.get("修行槽位"), "道侣.修行槽位")
        qualification_growth = _mapping(value.get("资质成长修正"), "道侣.资质成长修正")
        medicine_rules = _mapping(
            self._data.dataset("服丹规则").get("服丹"), "服丹/规则/服丹.json"
        )
        medicine_auto = _mapping(medicine_rules.get("自动用药"), "服丹.自动用药")
        return CompanionRules(
            _positive_affection(value.get("赠礼每件好感"), "道侣.赠礼每件好感"),
            _positive_affection(gift_rules.get("偏爱倍率"), "道侣.赠礼喜好.偏爱倍率"),
            _positive_affection(gift_rules.get("合意倍率"), "道侣.赠礼喜好.合意倍率"),
            _positive_int(value.get("同行上限"), "道侣.同行上限"),
            _positive_affection(invitation.get("好感要求"), "道侣.邀约.好感要求"),
            _text(
                invitation.get("首次邀约性别关系"),
                "道侣.邀约.首次邀约性别关系",
            ),
            _bool(
                invitation.get("再次邀约检查性别"),
                "道侣.邀约.再次邀约检查性别",
            ),
            _positive_affection(reward.get("触发好感"), "道侣.圆满回礼.触发好感"),
            _positive_int(
                reward.get("每名道侣终身次数"),
                "道侣.圆满回礼.每名道侣终身次数",
            ),
            MappingProxyType(
                {
                    category: _positive_int(
                        slots_value.get(category), f"道侣.修行槽位.{category}"
                    )
                    for category in ("功法", "真意", "气机")
                }
            ),
            Decimal(str(qualification_growth.get("最低倍率"))),
            Decimal(str(qualification_growth.get("最高倍率"))),
            _bool(medicine_auto.get("默认开启"), "服丹.自动用药.默认开启"),
        )

    def _load_plant_pool_meridians(self) -> Mapping[str, str]:
        rows = _sequence(
            self._data.dataset("炼药规则").get("归脉"),
            "炼丹/规则/归脉.json",
        )
        result: dict[str, str] = {}
        for raw in rows:
            row = _mapping(raw, "炼药归脉[]")
            pool_name = _text(row.get("灵植池"), "炼药归脉.灵植池")
            main = _text(row.get("本脉"), "炼药归脉.本脉")
            if pool_name in result:
                raise JsonDataError(f"炼药归脉重复定义灵植池：{pool_name}")
            result[pool_name] = main
        return MappingProxyType(result)

    def _realms(self) -> tuple[tuple[str, str, int, int], ...]:
        return tuple(
            (
                realm_id,
                _text(value.get("名称"), f"境界 {realm_id}.名称"),
                _positive_int(value.get("等级下限"), f"境界 {realm_id}.等级下限"),
                _positive_int(value.get("等级上限"), f"境界 {realm_id}.等级上限"),
            )
            for realm_id, value in self._data.entities("境界").items()
        )

    def _definition(
        self,
        companion_id: str,
        value: Mapping[str, object],
        realms: tuple[tuple[str, str, int, int], ...],
        grade_ids: frozenset[str],
    ) -> CompanionDefinition:
        record = self._data.entity_record("道侣", companion_id)
        location_name = _text(record.directory_owner, f"道侣 {companion_id}.归属地点")
        level = _positive_int(value.get("等级"), f"道侣 {companion_id}.等级")
        matches = tuple(
            (realm_id, realm_name)
            for realm_id, realm_name, minimum, maximum in realms
            if minimum <= level <= maximum
        )
        if len(matches) != 1:
            raise JsonDataError(f"道侣 {companion_id} 的等级无法唯一归属境界")
        identity = _mapping(value.get("身份"), f"道侣 {companion_id}.身份")
        join = _mapping(value.get("结交"), f"道侣 {companion_id}.结交")
        favorite_pools = tuple(
            _text(raw, f"道侣 {companion_id}.结交.灵植池")
            for raw in _sequence(join.get("灵植池"), "道侣.结交.灵植池")
        )
        favorite_items = frozenset(self._data.pool_members(favorite_pools, "基础物品"))
        if not favorite_items:
            raise JsonDataError(f"道侣 {companion_id} 的喜爱灵植池为空")
        for item_id in favorite_items:
            if self._data.entity_record("基础物品", item_id).number_category != "灵植":
                raise JsonDataError(f"道侣 {companion_id} 的喜爱池包含非灵植 {item_id}")
        try:
            favorite_meridians = {
                self._plant_pool_meridians[pool_name] for pool_name in favorite_pools
            }
        except KeyError as exc:
            raise JsonDataError(
                f"道侣 {companion_id} 的偏爱灵植池缺少炼药归脉：{exc.args[0]}"
            ) from exc
        acceptable_pools = tuple(
            sorted(
                pool_name
                for pool_name, main in self._plant_pool_meridians.items()
                if main in favorite_meridians and pool_name not in favorite_pools
            )
        )
        acceptable_items = frozenset(
            self._data.pool_members(acceptable_pools, "基础物品")
        ) - favorite_items
        reward_value = _mapping(join.get("圆满回礼"), "道侣.结交.圆满回礼")
        reward = CompanionReward(
            _text(reward_value.get("编号"), "圆满回礼.编号"),
            _text(reward_value.get("品级"), "圆满回礼.品级"),
            _positive_int(reward_value.get("数量"), "圆满回礼.数量"),
        )
        try:
            self._data.entity("基础物品", reward.item_id)
        except JsonDataError:
            self._data.entity("丹药", reward.item_id)
        if reward.grade_id not in grade_ids:
            raise JsonDataError(f"道侣 {companion_id} 使用未知回礼品级")
        fluctuation = _mapping(value.get("实力波动"), "道侣.实力波动")
        attributes = _mapping(value.get("属性覆盖"), "道侣.属性覆盖")
        cultivation_pools = MappingProxyType(
            {
                category: _text(
                    value.get(f"{category}池"), f"道侣 {companion_id}.{category}池"
                )
                for category in ("功法", "真意", "气机")
            }
        )
        for category, pool_name in cultivation_pools.items():
            if not self._data.pool_members((pool_name,), category):
                raise JsonDataError(f"道侣 {companion_id} 的{category}池为空")
        weapon = _mapping(value.get("本命武器"), f"道侣 {companion_id}.本命武器")
        weapon_laws = tuple(
            _text(raw, f"道侣 {companion_id}.本命武器.器律[]")
            for raw in _sequence(
                weapon.get("器律"),
                f"道侣 {companion_id}.本命武器.器律",
                allow_empty=True,
            )
        )
        for law_id in weapon_laws:
            self._data.entity("器律", law_id)
        qualification = _integer_range(value.get("资质范围"), "道侣.资质范围")
        multiplier_range = _integer_range(fluctuation.get("倍率"), "道侣.实力波动.倍率")
        realm_id, realm_name = matches[0]
        return CompanionDefinition(
            companion_id,
            _text(value.get("名称"), f"道侣 {companion_id}.名称"),
            _text(value.get("性别"), f"道侣 {companion_id}.性别"),
            _text(identity.get("称号"), f"道侣 {companion_id}.身份.称号"),
            _text(identity.get("立场"), f"道侣 {companion_id}.身份.立场"),
            _text(identity.get("性格方向"), f"道侣 {companion_id}.身份.性格方向"),
            _text(value.get("说明"), f"道侣 {companion_id}.说明"),
            location_name,
            realm_id,
            realm_name,
            level,
            _bool(identity.get("可交互"), f"道侣 {companion_id}.身份.可交互"),
            favorite_pools,
            favorite_items,
            acceptable_pools,
            acceptable_items,
            reward,
            CompanionDialogue(
                _text_sequence(identity.get("话语"), "道侣.身份.话语"),
                _text(join.get("喜好话语"), "道侣.结交.喜好话语"),
                _text_sequence(join.get("收礼话语"), "道侣.结交.收礼话语"),
                _text_sequence(join.get("婉拒话语"), "道侣.结交.婉拒话语"),
                _text(join.get("圆满话语"), "道侣.结交.圆满话语"),
                _text(join.get("邀约话语"), "道侣.结交.邀约话语"),
                _text(join.get("暂别话语"), "道侣.结交.暂别话语"),
            ),
            qualification,
            _text_sequence(fluctuation.get("属性"), "道侣.实力波动.属性"),
            multiplier_range,
            cultivation_pools,
            MappingProxyType(
                {
                    str(key): _number(raw, f"道侣 {companion_id}.属性覆盖.{key}")
                    for key, raw in attributes.items()
                }
            ),
            _text(weapon.get("名称"), f"道侣 {companion_id}.本命武器.名称"),
            _positive_int(weapon.get("等级"), f"道侣 {companion_id}.本命武器.等级"),
            _nonnegative_int(weapon.get("经验"), f"道侣 {companion_id}.本命武器.经验"),
            weapon_laws,
        )

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("道侣核心微服务尚未初始化")


def _relation_value(relation: CompanionRelation) -> dict[str, object]:
    value: dict[str, object] = {
        "当前好感": _affection_json(relation.current_affection),
        "赠礼累计": dict(relation.gift_totals),
    }
    if relation.first_full_at:
        value["首次圆满时间"] = relation.first_full_at
    if relation.first_invited_at:
        value["首次邀约时间"] = relation.first_invited_at
    return value


def _instance_value(
    instance: CompanionInstance,
    forging: ForgingService,
) -> dict[str, object]:
    stage_name = forging.weapon_stage(instance.weapon_level).name
    return {
        "境界": instance.realm_id,
        "等级": instance.level,
        "经验": instance.experience,
        "属性": dict(instance.attributes),
        "五行根性": dict(instance.five_elements),
        "修行槽": {
            category: list(content_ids)
            for category, content_ids in instance.cultivation.items()
        },
        "本命武器": {
            "名称": instance.weapon_name,
            "等级": instance.weapon_level,
            "经验": instance.weapon_experience,
            "器阶": stage_name,
            "器律": list(instance.weapon_laws),
        },
        "资质": instance.qualification,
        "属性倍率": dict(instance.attribute_multipliers),
        "突破记录": [dict(record) for record in instance.breakthrough_records],
        "资源": dict(instance.resources),
        "自动用药": instance.automatic_medicine,
        "待战战丹": _prepared_battle_value(instance.prepared_battle_medicine),
    }


def _prepared_battle_medicine(
    value: object, label: str
) -> PreparedBattleMedicine | None:
    if value is None:
        return None
    row = _state_mapping(value, label)
    if set(row) != {"编号", "品级"}:
        raise CompanionStateError(f"{label}字段不完整")
    return PreparedBattleMedicine(
        _state_text(row.get("编号"), f"{label}.编号"),
        _state_text(row.get("品级"), f"{label}.品级"),
    )


def _prepared_battle_value(
    value: PreparedBattleMedicine | None,
) -> dict[str, str] | None:
    if value is None:
        return None
    return {"编号": value.medicine_id, "品级": value.grade_id}


def _medicine_resource(value: object) -> str:
    result = str(value or "").strip()
    if result not in {"血气", "精神"}:
        raise CompanionCultivationError("恢复资源只能是血气或精神")
    return result


def _positive_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise CompanionCultivationError(f"{label}必须是正数")
    return float(value)


def _clean_number(value: float) -> int | float:
    return int(value) if value.is_integer() else round(value, 4)


def _scaled_number(value: float, multiplier: int) -> int | float:
    result = float(value) * multiplier / 100
    return int(result) if result.is_integer() else round(result, 4)


def _qualification_multiplier(
    instance: CompanionInstance,
    definition: CompanionDefinition,
    rules: CompanionRules,
) -> float:
    return _qualification_multiplier_value(instance.qualification, definition, rules)


def _qualification_multiplier_value(
    qualification: int,
    definition: CompanionDefinition,
    rules: CompanionRules,
) -> float:
    minimum, maximum = definition.qualification_range
    if minimum == maximum:
        return 1.0
    progress = Decimal(qualification - minimum) / Decimal(maximum - minimum)
    result = rules.qualification_growth_minimum + progress * (
        rules.qualification_growth_maximum - rules.qualification_growth_minimum
    )
    return float(result)


def _add_numbers(
    source: Mapping[str, int | float], additions: Mapping[str, int | float]
) -> dict[str, int | float]:
    result = dict(source)
    for name, raw in additions.items():
        before = result.get(str(name), 0)
        value = float(before) + float(raw)
        result[str(name)] = int(value) if value.is_integer() else round(value, 4)
    return result


def _request_nonnegative_int(value: object, label: str) -> int:
    return nonnegative_int(value, label, error=CompanionCultivationError)


def _request_ratio(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= value <= 1
    ):
        raise CompanionCultivationError(f"{label}必须在0至1之间")
    return float(value)


def _bounded_resource(value: object, maximum: object, label: str) -> int | float:
    raw = _number(value, label)
    upper = _number(maximum, f"{label}上限")
    bounded = min(max(0.0, float(raw)), max(0.0, float(upper)))
    return int(bounded) if bounded.is_integer() else round(bounded, 3)


def _affection_json(value: Decimal) -> int | float:
    normalized = _quantize(value)
    return (
        int(normalized) if normalized == normalized.to_integral() else float(normalized)
    )


def _display_affection(value: Decimal) -> str:
    return format(_quantize(value), "f").rstrip("0").rstrip(".") or "0"


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_AFFECTION_QUANTUM, rounding=ROUND_HALF_UP)


def _positive_affection(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise JsonDataError(f"{label}必须是十进制数") from exc
    if not result.is_finite() or result <= 0:
        raise JsonDataError(f"{label}必须大于0")
    return _quantize(result)


def _state_affection(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CompanionStateError(f"{label}必须是十进制数") from exc
    if not result.is_finite() or result < 0:
        raise CompanionStateError(f"{label}不能小于0")
    return _quantize(result)


def _state_mapping(value: object, label: str) -> Mapping[str, object]:
    return mapping(value, label, error=CompanionStateError)


def _state_five_elements(value: object) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise CompanionStateError("道侣实例.五行根性必须是对象")
    expected = {"木", "火", "土", "金", "水"}
    if set(value) != expected:
        raise CompanionStateError("道侣实例.五行根性必须完整包含木火土金水")
    result = {str(key): float(raw) for key, raw in value.items()}
    if any(raw < 0 or raw > 100 for raw in result.values()) or abs(sum(result.values()) - 100) > 1e-6:
        raise CompanionStateError("道侣实例.五行根性每项须在0到100且总和为100")
    return result


def _sequence(
    value: object,
    label: str,
    *,
    allow_empty: bool = False,
) -> tuple[object, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError(f"{label}必须是数组")
    result = tuple(value)
    if not result and not allow_empty:
        raise JsonDataError(f"{label}不能为空")
    return result


def _state_sequence(
    value: object,
    label: str,
    *,
    allow_empty: bool = False,
) -> tuple[object, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CompanionStateError(f"{label}必须是数组")
    result = tuple(value)
    if not result and not allow_empty:
        raise CompanionStateError(f"{label}不能为空")
    return result


def _text_sequence(value: object, label: str) -> tuple[str, ...]:
    return tuple(_text(raw, f"{label}[]") for raw in _sequence(value, label))


def _integer_range(value: object, label: str) -> tuple[int, int]:
    values = _sequence(value, label)
    if len(values) != 2:
        raise JsonDataError(f"{label}必须包含下限和上限")
    minimum = _positive_int(values[0], f"{label}.下限")
    maximum = _positive_int(values[1], f"{label}.上限")
    if minimum > maximum:
        raise JsonDataError(f"{label}下限不能大于上限")
    return minimum, maximum


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JsonDataError(f"{label}必须是非空字符串")
    return value.strip()


def _state_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CompanionStateError(f"{label}不能为空")
    return text


def _optional_text(value: object) -> str:
    return str(value or "").strip()


def _number(value: object, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JsonDataError(f"{label}必须是数值")
    return value


def _state_positive_int(value: object, label: str) -> int:
    return positive_int(value, label, error=CompanionStateError)


def _state_nonnegative_int(value: object, label: str) -> int:
    return nonnegative_int(value, label, error=CompanionStateError)


def _state_number(value: object, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CompanionStateError(f"{label}必须是数值")
    return value


def _state_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise CompanionStateError(f"{label}必须是布尔值")
    return value


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise JsonDataError(f"{label}必须是布尔值")
    return value


def _normalize(value: object) -> str:
    return "".join(str(value or "").split()).casefold()


def _user_id(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("user_id不能为空")
    return normalized


__all__ = [
    "ACTIVE_KEY",
    "ACTIVE_STATE",
    "INSTANCE_STATE",
    "RELATION_STATE",
    "CompanionService",
]
