"""解释炼器 JSON，并原子完成材料消耗与器律产出。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import ceil
from types import MappingProxyType

from game.core.asset import (
    AssetEntry,
    AssetService,
    AssetStateError,
    InventoryAdjustment,
    InventoryChangeError,
)
from game.core.data import ContractSet, JsonDataError, JsonDataService
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    StateConflictError,
    TransactionCommand,
)
from game.core.innate_treasure import (
    InnateTreasureActivation,
    InnateTreasureService,
)
from game.core.location import LocationService
from game.core.world import LocationQuery, WorldService
from game.core.world import WORLD_CONTRACT_DATASET, WORLD_CONTRACT_PATH

from .contracts import (
    ForgingArtisan,
    ForgingAssessment,
    ForgingConflictError,
    ForgingError,
    ForgingLaw,
    ForgingLawEntry,
    ForgingLawList,
    ForgingMaterial,
    ForgingMaterialError,
    ForgingMissingMaterial,
    ForgingOverview,
    ForgingPreview,
    ForgingResult,
    ForgingStatus,
    ForgingUnavailableError,
    WeaponAdvance,
    WeaponStage,
)

_LAW_STAGES = ("灵器", "法器", "法宝", "后天灵宝")
_SECONDARY_COST = 1_000_000_000
_GRADE_COST = 100_000


@dataclass(frozen=True)
class _MaterialIdentity:
    item_id: str
    name: str
    primary_trait: str
    secondary_trait: str = ""


@dataclass(frozen=True)
class _Choice:
    identity: _MaterialIdentity
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


class ForgingService:
    """炼器内容、本命武器成长和炼制事务的唯一解释入口。"""

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
        self._weapon_rule: Mapping[str, object] = MappingProxyType({})
        self._stages: tuple[WeaponStage, ...] = ()
        self._stage_by_name: Mapping[str, WeaponStage] = MappingProxyType({})
        self._laws: Mapping[str, ForgingLaw] = MappingProxyType({})
        self._law_by_name: Mapping[str, str] = MappingProxyType({})
        self._methods: Mapping[str, tuple[str, tuple[str, ...]]] = MappingProxyType({})
        self._artisans: Mapping[str, ForgingArtisan] = MappingProxyType({})
        self._beast_materials: Mapping[str, _MaterialIdentity] = MappingProxyType({})
        self._mineral_materials: Mapping[str, _MaterialIdentity] = MappingProxyType({})

    def initialize(self) -> ForgingStatus:
        if self._initialized:
            raise RuntimeError("炼器核心微服务已经初始化")
        for ready, label in (
            (self._data.status().loaded, "JSON 数据微服务"),
            (self._database.status().initialized, "核心数据库"),
            (self._asset.status().initialized, "玩家资产核心"),
            (self._world.status().initialized, "世界核心"),
            (self._location.status().initialized, "位置核心"),
            (self._innate_treasure.status().initialized, "先天灵宝核心"),
        ):
            if not ready:
                raise RuntimeError(f"{label}必须先于炼器核心启动")
        rules = self._data.dataset("炼器规则")
        self._weapon_rule = MappingProxyType(
            dict(_mapping(rules.get("本命武器"), "炼器规则.本命武器"))
        )
        law_rule = _mapping(rules.get("器则"), "炼器规则.器则")
        self._stages = tuple(
            _weapon_stage(_mapping(raw, "器则.器阶[]"))
            for raw in _sequence(law_rule.get("器阶"), "器则.器阶")
        )
        self._stage_by_name = MappingProxyType(
            {stage.name: stage for stage in self._stages}
        )
        self._methods = MappingProxyType(self._load_methods(rules.get("铸法")))
        self._beast_materials = MappingProxyType(
            self._load_beast_materials(rules.get("归引"))
        )
        self._mineral_materials = MappingProxyType(
            self._load_mineral_materials(rules.get("归脉"))
        )
        self._laws = MappingProxyType(self._load_laws())
        self._law_by_name = MappingProxyType(
            {law.name: law_id for law_id, law in self._laws.items()}
        )
        self._artisans = MappingProxyType(self._load_artisans())
        self._validate_static_rules(law_rule)
        self._initialized = True
        return self.status()

    def status(self) -> ForgingStatus:
        return ForgingStatus(
            self._initialized,
            len(self._laws),
            len(self._methods),
            len(self._artisans),
            len(self._beast_materials),
            len(self._mineral_materials),
            int(self._weapon_rule.get("等级上限") or 0),
        )

    def laws(self, stage: str) -> tuple[ForgingLaw, ...]:
        self._require_initialized()
        normalized = str(stage or "").strip()
        if normalized not in _LAW_STAGES:
            raise ForgingError(f"未知器律器阶：{normalized or '<空>'}")
        return tuple(
            sorted(
                (law for law in self._laws.values() if law.stage == normalized),
                key=lambda value: value.law_id,
            )
        )

    def assess(
        self, identifier: str, entries: tuple[AssetEntry, ...]
    ) -> ForgingAssessment:
        self._require_initialized()
        law = self._resolve_law(identifier)
        stage = self._stage_by_name[law.stage]
        beasts, missing_beasts, _ = self._match(
            law.beast_traits,
            entries,
            self._beast_materials,
            stage.minimum_beast_grade_id,
            allow_secondary=False,
        )
        minerals, missing_minerals, secondary_count = self._match(
            law.mineral_traits,
            entries,
            self._mineral_materials,
            stage.minimum_mineral_grade_id,
            allow_secondary=True,
        )
        missing = list(missing_beasts + missing_minerals)
        if not missing and secondary_count > stage.secondary_substitution_limit:
            missing.append(
                ForgingMissingMaterial(
                    "灵矿",
                    "本脉材料",
                    secondary_count - stage.secondary_substitution_limit,
                )
            )
        return ForgingAssessment(
            law,
            beasts,
            minerals,
            tuple(missing),
            secondary_count,
            stage.secondary_substitution_limit,
            not missing,
        )

    def initial_weapon_level(self) -> int:
        self._require_initialized()
        return _positive_int(self._weapon_rule.get("初始等级"), "本命武器.初始等级")

    def weapon_experience_required(self, level: int) -> int:
        self._require_initialized()
        maximum = _positive_int(self._weapon_rule.get("等级上限"), "本命武器.等级上限")
        if (
            isinstance(level, bool)
            or not isinstance(level, int)
            or not 1 <= level <= maximum
        ):
            raise ForgingError(f"本命武器等级必须在1至{maximum}之间")
        if level == maximum:
            return 0
        curve = _mapping(self._weapon_rule.get("经验"), "本命武器.经验")
        base = math.floor(
            _number(curve.get("幂次基数"), "本命武器.经验.幂次基数")
            * level ** _number(curve.get("等级幂次"), "本命武器.经验.等级幂次")
            + _number(curve.get("等级基数"), "本命武器.经验.等级基数") * level
        )
        late = _mapping(curve.get("后段"), "本命武器.经验.后段")
        start = _positive_int(late.get("起始等级"), "本命武器.经验.后段.起始等级")
        if level <= start:
            return max(1, base)
        progress = (level - start) / _positive_int(
            late.get("跨度"), "本命武器.经验.后段.跨度"
        )
        multiplier = 1.0
        for prefix in ("中段", "高段", "终段"):
            multiplier += _number(
                late.get(f"{prefix}系数"), f"本命武器.经验.后段.{prefix}系数"
            ) * progress ** _number(
                late.get(f"{prefix}幂次"), f"本命武器.经验.后段.{prefix}幂次"
            )
        return max(1, math.floor(base * multiplier))

    def advance_weapon(
        self, *, level: int, experience: int, gained: int
    ) -> WeaponAdvance:
        self._require_initialized()
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (level, experience, gained)
        ):
            raise ForgingError("本命武器等级和经验必须是整数")
        if level < 1 or experience < 0 or gained < 0:
            raise ForgingError("本命武器等级必须为正，经验不能为负")
        before = self.weapon_stage(level)
        maximum = _positive_int(self._weapon_rule.get("等级上限"), "本命武器.等级上限")
        current_level = level
        current_experience = experience + gained
        while current_level < maximum:
            required = self.weapon_experience_required(current_level)
            if current_experience < required:
                break
            current_experience -= required
            current_level += 1
        after = self.weapon_stage(current_level)
        return WeaponAdvance(
            level,
            current_level,
            experience,
            current_experience,
            gained,
            before.name,
            after.name,
            before.open_law_slots,
            after.open_law_slots,
        )

    def weapon_stage(self, level: int) -> WeaponStage:
        self._require_initialized()
        if isinstance(level, bool) or not isinstance(level, int):
            raise ForgingError("本命武器等级必须是整数")
        for stage in self._stages:
            if stage.minimum_level <= level <= stage.maximum_level:
                return stage
        raise ForgingError(f"本命武器等级没有对应器阶：{level}")

    def weapon_attack(self, level: int, *, base_attack: float | None = None) -> float:
        self.weapon_stage(level)
        base = (
            _number(self._weapon_rule.get("基础攻击"), "本命武器.基础攻击")
            if base_attack is None
            else _request_number(base_attack, "本命武器基础攻击")
        )
        per_level = _number(self._weapon_rule.get("每级攻击"), "本命武器.每级攻击")
        return base + per_level * (level - 1)

    def law_allowed(self, weapon_level: int, law_stage: str) -> bool:
        current = self.weapon_stage(weapon_level)
        normalized = str(law_stage or "").strip()
        order = {stage.name: index for index, stage in enumerate(self._stages)}
        if normalized not in order:
            raise ForgingError(f"未知器律器阶：{normalized or '<空>'}")
        return order[normalized] <= order[current.name]

    async def overview(self, user_id: str) -> ForgingOverview:
        normalized = _request_text(user_id, "user_id")
        location_name, artisan = await self._current_artisan(normalized)
        return ForgingOverview(
            normalized,
            location_name,
            artisan,
            tuple(
                (stage, sum(law.stage == stage for law in self._laws.values()))
                for stage in _LAW_STAGES
            ),
        )

    async def list_laws(self, user_id: str, stage: str) -> ForgingLawList:
        normalized = _request_text(user_id, "user_id")
        normalized_stage = str(stage or "").strip()
        if normalized_stage not in _LAW_STAGES:
            raise ForgingError(f"未知器律器阶：{normalized_stage or '<空>'}")
        location_name, artisan = await self._current_artisan(normalized)
        entries = await self._material_entries(normalized)
        laws = sorted(
            (law for law in self._laws.values() if law.stage == normalized_stage),
            key=lambda law: law.law_id,
        )
        return ForgingLawList(
            normalized,
            location_name,
            artisan,
            normalized_stage,
            tuple(
                ForgingLawEntry(
                    law,
                    (
                        preview := self._build_preview(
                            normalized, location_name, artisan, law, entries
                        )
                    ).can_forge,
                    sum(missing.quantity for missing in preview.missing_materials),
                )
                for law in laws
            ),
        )

    async def preview(self, user_id: str, identifier: str) -> ForgingPreview:
        normalized = _request_text(user_id, "user_id")
        law = self._resolve_law(identifier)
        location_name, artisan = await self._current_artisan(normalized)
        entries = await self._material_entries(normalized)
        return self._build_preview(normalized, location_name, artisan, law, entries)

    async def forge(
        self, user_id: str, request_id: str, identifier: str
    ) -> ForgingResult:
        normalized = _request_text(user_id, "user_id")
        request = _request_text(request_id, "request_id")
        law = self._resolve_law(identifier)
        committed = await self._database.committed_transaction(normalized, request)
        if committed is not None:
            if (
                committed.receipt.business_type != "炼器"
                or committed.payload.get("器律编号") != law.law_id
            ):
                raise ForgingConflictError("请求编号已经用于其他操作")
            return self._replayed_result(normalized, law, committed.payload)
        preview = await self.preview(normalized, law.law_id)
        if not preview.can_forge:
            raise ForgingMaterialError("纳戒中的兽宝和灵矿不足以炼成该器律")
        adjustments = [
            InventoryAdjustment(material.item_id, material.grade_id, -material.quantity)
            for material in preview.beast_materials + preview.mineral_materials
        ]
        activation: InnateTreasureActivation | None = None
        treasure_effect = await self._innate_treasure.effect(normalized, "炼器成功")
        if treasure_effect is not None:
            treasure, effect = treasure_effect
            if effect.ability == "返还灵矿":
                mineral_total = sum(item.quantity for item in preview.mineral_materials)
                return_total = min(
                    mineral_total,
                    max(
                        int(effect.values["最低数量"]),
                        ceil(mineral_total * float(effect.values["比例"])),
                    ),
                )
                remaining = return_total
                returned: list[str] = []
                for material in sorted(
                    preview.mineral_materials,
                    key=lambda item: (
                        -item.quantity,
                        self._asset.grade(item.grade_id).order,
                        item.item_id,
                    ),
                ):
                    quantity = min(material.quantity, remaining)
                    if quantity:
                        adjustments.append(
                            InventoryAdjustment(
                                material.item_id, material.grade_id, quantity
                            )
                        )
                        returned.append(f"{material.grade_name}{material.name} × {quantity}")
                        remaining -= quantity
                    if not remaining:
                        break
                activation = InnateTreasureActivation(
                    treasure.treasure_id,
                    treasure.name,
                    treasure.authority,
                    "返还" + "、".join(returned),
                )
        try:
            inventory = await self._asset.plan_inventory_changes(
                normalized, tuple(adjustments)
            )
            reserve = await self._asset.plan_law_reserve_acquisition(
                normalized, preview.law.law_id
            )
            payload = {
                "地点": preview.location_name,
                "工匠编号": preview.artisan.artisan_id,
                "器律编号": preview.law.law_id,
                "器藏原数量": reserve.quantity_before,
                "器藏现数量": reserve.quantity_after,
                "兽宝": [_material_payload(item) for item in preview.beast_materials],
                "灵矿": [_material_payload(item) for item in preview.mineral_materials],
                "先天灵宝": _activation_payload(activation),
            }
            receipt = await self._database.commit(
                TransactionCommand(
                    normalized,
                    request,
                    "炼器",
                    inventory.operations + (reserve.operation,),
                    payload,
                )
            )
        except StateConflictError as exc:
            raise ForgingConflictError("纳戒或器藏已经变化，请重新审材") from exc
        except IdempotencyConflictError as exc:
            raise ForgingConflictError("请求编号已经用于其他操作") from exc
        except (AssetStateError, InventoryChangeError) as exc:
            raise ForgingMaterialError(str(exc)) from exc
        return ForgingResult(
            preview,
            reserve.quantity_before,
            reserve.quantity_after,
            receipt.replayed,
            activation,
        )

    def _replayed_result(
        self,
        user_id: str,
        law: ForgingLaw,
        payload: Mapping[str, object],
    ) -> ForgingResult:
        try:
            location_name = _payload_text(payload.get("地点"), "炼器事务.地点")
            artisan = self._artisans[location_name]
            if artisan.artisan_id != _payload_text(
                payload.get("工匠编号"), "炼器事务.工匠编号"
            ):
                raise ValueError("炼器事务工匠与地点不一致")
            beasts = _payload_materials(
                payload.get("兽宝"), self._beast_materials, self._asset, "兽宝"
            )
            minerals = _payload_materials(
                payload.get("灵矿"), self._mineral_materials, self._asset, "灵矿"
            )
            before = _payload_nonnegative_int(
                payload.get("器藏原数量"), "炼器事务.器藏原数量"
            )
            after = _payload_positive_int(
                payload.get("器藏现数量"), "炼器事务.器藏现数量"
            )
            activation = _payload_activation(payload.get("先天灵宝"))
        except (KeyError, TypeError, ValueError) as exc:
            raise ForgingConflictError("已提交炼器事务无法还原") from exc
        stage = self._stage_by_name[law.stage]
        preview = ForgingPreview(
            user_id,
            location_name,
            artisan,
            law,
            beasts,
            minerals,
            (),
            sum(material.relation == "旁脉" for material in minerals),
            stage.secondary_substitution_limit,
            True,
        )
        return ForgingResult(preview, before, after, True, activation)

    def _build_preview(
        self,
        user_id: str,
        location_name: str,
        artisan: ForgingArtisan,
        law: ForgingLaw,
        entries: tuple[AssetEntry, ...],
    ) -> ForgingPreview:
        value = self.assess(law.law_id, entries)
        return ForgingPreview(
            user_id,
            location_name,
            artisan,
            value.law,
            value.beast_materials,
            value.mineral_materials,
            value.missing_materials,
            value.secondary_substitutions,
            value.secondary_substitution_limit,
            value.can_forge,
        )

    def _match(
        self,
        traits: tuple[str, ...],
        entries: tuple[AssetEntry, ...],
        identities: Mapping[str, _MaterialIdentity],
        minimum_grade_id: str,
        *,
        allow_secondary: bool,
    ) -> tuple[
        tuple[ForgingMaterial, ...],
        tuple[ForgingMissingMaterial, ...],
        int,
    ]:
        minimum_order = self._asset.grade(minimum_grade_id).order
        by_item: dict[str, list[AssetEntry]] = {}
        for entry in entries:
            if entry.content_id in identities:
                by_item.setdefault(entry.content_id, []).append(entry)
        choices: list[_Choice] = []
        for item_rank, item_id in enumerate(sorted(by_item)):
            identity = identities[item_id]
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
                    relation, quantity = ("本脉" if allow_secondary else "兽脉"), 1
                elif allow_secondary and identity.secondary_trait == trait:
                    relation, quantity = "旁脉", 2
                if not relation:
                    continue
                entry = next(
                    (value for value in stacks if value.quantity >= quantity), None
                )
                if entry is not None:
                    choices.append(
                        _Choice(identity, entry, slot, trait, relation, quantity)
                    )
        matched = _minimum_cost_matching(
            tuple(sorted(by_item)),
            len(traits),
            choices,
            self._asset,
        )
        materials = tuple(
            ForgingMaterial(
                choice.identity.item_id,
                choice.identity.name,
                choice.entry.grade_id,
                choice.entry.grade_name,
                choice.trait,
                choice.relation,
                choice.quantity,
            )
            for choice in sorted(matched.values(), key=lambda value: value.slot)
        )
        missing_traits = [
            trait for index, trait in enumerate(traits) if index not in matched
        ]
        missing_counts: dict[str, int] = {}
        for trait in missing_traits:
            missing_counts[trait] = missing_counts.get(trait, 0) + 1
        category = "灵矿" if allow_secondary else "兽宝"
        missing = tuple(
            ForgingMissingMaterial(category, trait, quantity)
            for trait, quantity in missing_counts.items()
        )
        return (
            materials,
            missing,
            sum(material.relation == "旁脉" for material in materials),
        )

    async def _material_entries(self, user_id: str) -> tuple[AssetEntry, ...]:
        snapshot = await self._asset.snapshot(user_id)
        return tuple(
            entry
            for entry in snapshot.entries
            if entry.category == "基础物品" and entry.subcategory in {"兽宝", "灵矿"}
        )

    async def _current_artisan(self, user_id: str) -> tuple[str, ForgingArtisan]:
        self._require_initialized()
        current = await self._location.current(user_id)
        place = self._world.locate(LocationQuery(xy=current.xy))
        if not place.location_name or "锻造" not in place.available_functions:
            raise ForgingUnavailableError("此地没有能够主持炼器的工匠")
        artisan = self._artisans.get(place.location_name)
        if artisan is None:
            raise ForgingUnavailableError("此地没有能够主持炼器的工匠")
        return place.location_name, artisan

    def _resolve_law(self, identifier: str) -> ForgingLaw:
        self._require_initialized()
        query = str(identifier or "").strip()
        law = self._laws.get(query)
        if law is None:
            law = self._laws.get(self._law_by_name.get(query, ""))
        if law is None:
            raise ForgingError(f"未找到唯一器律：{query or '<空>'}")
        return law

    def _load_methods(self, value: object) -> dict[str, tuple[str, tuple[str, ...]]]:
        result: dict[str, tuple[str, tuple[str, ...]]] = {}
        for raw in _sequence(value, "炼器规则.铸法"):
            row = _mapping(raw, "铸法[]")
            name = _text(row.get("名称"), "铸法.名称")
            if name in result:
                raise JsonDataError(f"铸法名称重复：{name}")
            traits: list[str] = []
            for material in _sequence(row.get("辅材"), f"铸法 {name}.辅材"):
                material_row = _mapping(material, f"铸法 {name}.辅材[]")
                trait = _text(material_row.get("铸脉"), f"铸法 {name}.铸脉")
                traits.extend(
                    [trait]
                    * _positive_int(material_row.get("份数"), f"铸法 {name}.份数")
                )
            result[name] = (_text(row.get("器阶"), f"铸法 {name}.器阶"), tuple(traits))
        return result

    def _load_beast_materials(self, value: object) -> dict[str, _MaterialIdentity]:
        result: dict[str, _MaterialIdentity] = {}
        for raw in _sequence(value, "炼器规则.归引"):
            row = _mapping(raw, "归引[]")
            pool = _text(row.get("兽宝池"), "归引.兽宝池")
            trait = _text(row.get("兽脉"), "归引.兽脉")
            for item_id in self._data.pool_members((pool,), "基础物品"):
                if item_id in result:
                    raise JsonDataError(f"兽宝重复归引：{item_id}")
                result[item_id] = _MaterialIdentity(
                    item_id,
                    _entity_name(self._data, item_id),
                    trait,
                )
        return result

    def _load_mineral_materials(self, value: object) -> dict[str, _MaterialIdentity]:
        result: dict[str, _MaterialIdentity] = {}
        for raw in _sequence(value, "炼器规则.归脉"):
            row = _mapping(raw, "归脉[]")
            pool = _text(row.get("灵矿池"), "归脉.灵矿池")
            primary = _text(row.get("本脉"), "归脉.本脉")
            secondary = _text(row.get("旁脉"), "归脉.旁脉")
            for item_id in self._data.pool_members((pool,), "基础物品"):
                if item_id in result:
                    raise JsonDataError(f"灵矿重复归脉：{item_id}")
                result[item_id] = _MaterialIdentity(
                    item_id,
                    _entity_name(self._data, item_id),
                    primary,
                    secondary,
                )
        return result

    def _load_laws(self) -> dict[str, ForgingLaw]:
        result: dict[str, ForgingLaw] = {}
        names: set[str] = set()
        for law_id, raw in self._data.entities("器律").items():
            name = _text(raw.get("名称"), f"器律 {law_id}.名称")
            if name in names:
                raise JsonDataError(f"器律名称重复：{name}")
            names.add(name)
            stage = _text(raw.get("器阶"), f"器律 {law_id}.器阶")
            method_name = _text(raw.get("铸法"), f"器律 {law_id}.铸法")
            method = self._methods.get(method_name)
            if method is None:
                raise JsonDataError(f"器律 {name} 引用不存在铸法：{method_name}")
            if method[0] != stage:
                raise JsonDataError(f"器律 {name} 的器阶与铸法不一致")
            result[law_id] = ForgingLaw(
                law_id,
                name,
                stage,
                method_name,
                _texts(raw.get("兽引"), f"器律 {name}.兽引"),
                method[1],
            )
        return result

    def _load_artisans(self) -> dict[str, ForgingArtisan]:
        result: dict[str, ForgingArtisan] = {}
        contract = ContractSet.from_dataset(
            self._data.dataset(WORLD_CONTRACT_DATASET), WORLD_CONTRACT_PATH
        )
        for artisan_id, raw in self._data.entities("炼器工匠").items():
            contract.validate(raw, "炼器工匠", f"炼器工匠 {artisan_id}")
            location = self._data.entity_record("炼器工匠", artisan_id).directory_owner
            if not location:
                raise JsonDataError(f"炼器工匠 {artisan_id} 缺少地点目录归属")
            if location in result:
                raise JsonDataError(f"同一地点不能有多名执炉工匠：{location}")
            result[location] = ForgingArtisan(
                artisan_id,
                _text(raw.get("名称"), f"炼器工匠 {artisan_id}.名称"),
                location,
                _text(raw.get("称号"), f"炼器工匠 {artisan_id}.称号"),
                _text(raw.get("炉名"), f"炼器工匠 {artisan_id}.炉名"),
                _text(raw.get("工艺流派"), f"炼器工匠 {artisan_id}.工艺流派"),
                _text(raw.get("话语风格"), f"炼器工匠 {artisan_id}.话语风格"),
                _speech(raw.get("话语"), f"炼器工匠 {artisan_id}.话语"),
            )
        return result

    def _validate_static_rules(self, law_rule: Mapping[str, object]) -> None:
        maximum = _positive_int(self._weapon_rule.get("等级上限"), "本命武器.等级上限")
        if maximum != 100:
            raise JsonDataError("当前本命武器等级上限必须为100")
        if tuple(stage.name for stage in self._stages) != ("凡器",) + _LAW_STAGES:
            raise JsonDataError("器阶必须依次为凡器、灵器、法器、法宝、后天灵宝")
        expected_level = 1
        for stage in self._stages:
            if stage.minimum_level != expected_level:
                raise JsonDataError("器阶等级范围必须连续且从1开始")
            expected_level = stage.maximum_level + 1
        if expected_level != maximum + 1:
            raise JsonDataError("器阶等级范围没有完整覆盖本命武器等级")
        for law in self._laws.values():
            stage = self._stage_by_name.get(law.stage)
            if stage is None or law.stage == "凡器":
                raise JsonDataError(f"器律使用未知器阶：{law.name} -> {law.stage}")
            if len(law.beast_traits) != stage.beast_requirement_count:
                raise JsonDataError(f"器律兽引数量与器阶不一致：{law.name}")
            if (
                not stage.mineral_requirement_range[0]
                <= len(law.mineral_traits)
                <= stage.mineral_requirement_range[1]
            ):
                raise JsonDataError(f"器律矿材份数与器阶不一致：{law.name}")
        world_locations = {
            location.name: location for location in self._world.map_view().locations
        }
        forging_locations = {
            name
            for name, location in world_locations.items()
            if "锻造" in location.available_functions
        }
        if set(self._artisans) != forging_locations:
            missing = forging_locations - set(self._artisans)
            extra = set(self._artisans) - forging_locations
            raise JsonDataError(
                f"锻造地点与工匠不一一对应：缺少{sorted(missing)}，多余{sorted(extra)}"
            )
        beast_ids = _item_ids(self._data, "兽宝")
        mineral_ids = _item_ids(self._data, "灵矿")
        if set(self._beast_materials) != beast_ids:
            raise JsonDataError("归引没有完整且唯一覆盖全部兽宝")
        if set(self._mineral_materials) != mineral_ids:
            raise JsonDataError("归脉没有完整且唯一覆盖全部灵矿")
        forging = _mapping(law_rule.get("炼制"), "器则.炼制")
        if (
            forging.get("产出数量") != 1
            or forging.get("进入") != "器藏"
            or forging.get("失败") != "不消耗不产出"
        ):
            raise JsonDataError("炼器核心只支持一次产出一份器律并收入器藏")

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("炼器核心微服务尚未初始化")


# 本函数与 `game/core/alchemy/service.py` 的同名函数**逐字相同**（差异只有换行格式）。
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
                    if (
                        edge.capacity
                        and distances[origin] + edge.cost < distances[edge.target]
                    ):
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


def _material_payload(material: ForgingMaterial) -> dict[str, object]:
    return {
        "编号": material.item_id,
        "品级": material.grade_id,
        "数量": material.quantity,
        "脉性": material.trait,
        "关系": material.relation,
    }


def _activation_payload(
    activation: InnateTreasureActivation | None,
) -> dict[str, str] | None:
    if activation is None:
        return None
    return {
        "编号": activation.treasure_id,
        "名称": activation.name,
        "权柄": activation.authority,
        "结果": activation.summary,
    }


def _payload_activation(value: object) -> InnateTreasureActivation | None:
    if value is None:
        return None
    raw = _mapping(value, "炼器事务.先天灵宝")
    return InnateTreasureActivation(
        _payload_text(raw.get("编号"), "炼器事务.先天灵宝.编号"),
        _payload_text(raw.get("名称"), "炼器事务.先天灵宝.名称"),
        _payload_text(raw.get("权柄"), "炼器事务.先天灵宝.权柄"),
        _payload_text(raw.get("结果"), "炼器事务.先天灵宝.结果"),
    )


def _payload_materials(
    value: object,
    identities: Mapping[str, _MaterialIdentity],
    asset: AssetService,
    label: str,
) -> tuple[ForgingMaterial, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"炼器事务.{label}必须是数组")
    result: list[ForgingMaterial] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise TypeError(f"炼器事务.{label}材料必须是对象")
        item_id = _payload_text(raw.get("编号"), f"炼器事务.{label}.编号")
        identity = identities.get(item_id)
        if identity is None:
            raise ValueError(f"炼器事务.{label}引用未知材料")
        grade = asset.grade(_payload_text(raw.get("品级"), f"炼器事务.{label}.品级"))
        result.append(
            ForgingMaterial(
                item_id,
                identity.name,
                grade.grade_id,
                grade.name,
                _payload_text(raw.get("脉性"), f"炼器事务.{label}.脉性"),
                _payload_text(raw.get("关系"), f"炼器事务.{label}.关系"),
                _payload_positive_int(raw.get("数量"), f"炼器事务.{label}.数量"),
            )
        )
    return tuple(result)


def _payload_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空文本")
    return value.strip()


def _payload_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label}必须是正整数")
    return value


def _payload_nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label}必须是非负整数")
    return value


def _weapon_stage(value: Mapping[str, object]) -> WeaponStage:
    bounds = _integer_pair(value.get("等级范围"), "器阶.等级范围")
    minerals = _integer_pair(value.get("矿材份数"), "器阶.矿材份数")
    return WeaponStage(
        _text(value.get("名称"), "器阶.名称"),
        bounds[0],
        bounds[1],
        _nonnegative_int(value.get("开放器律孔"), "器阶.开放器律孔"),
        _nonnegative_int(value.get("兽引数量"), "器阶.兽引数量"),
        minerals,
        _nonnegative_int(value.get("旁脉替代上限"), "器阶.旁脉替代上限"),
        _text(value.get("最低兽宝品级"), "器阶.最低兽宝品级"),
        _text(value.get("最低灵矿品级"), "器阶.最低灵矿品级"),
    )


def _item_ids(data: JsonDataService, category: str) -> set[str]:
    return {
        item_id
        for item_id in data.entities("基础物品")
        if data.entity_record("基础物品", item_id).number_category == category
    }


def _entity_name(data: JsonDataService, item_id: str) -> str:
    return _text(data.entity("基础物品", item_id).get("名称"), f"物品 {item_id}.名称")


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return value


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError(f"{label}必须是数组")
    return tuple(value)


def _texts(value: object, label: str) -> tuple[str, ...]:
    return tuple(_text(raw, label) for raw in _sequence(value, label))


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JsonDataError(f"{label}必须是非空文本")
    return value.strip()


def _speech(value: object, label: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    expected = {"总览", "审材", "齐备", "不足", "完成"}
    if set(value) != expected:
        raise JsonDataError(f"{label}必须完整包含：{'、'.join(sorted(expected))}")
    return MappingProxyType({key: _text(value[key], f"{label}.{key}") for key in expected})


def _request_text(value: object, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ForgingError(f"{label}不能为空")
    return result


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JsonDataError(f"{label}必须是数值")
    return float(value)


def _request_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ForgingError(f"{label}必须是数值")
    return float(value)


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise JsonDataError(f"{label}必须是正整数")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise JsonDataError(f"{label}必须是非负整数")
    return value


def _integer_pair(value: object, label: str) -> tuple[int, int]:
    values = _sequence(value, label)
    if len(values) != 2 or any(
        isinstance(raw, bool) or not isinstance(raw, int) for raw in values
    ):
        raise JsonDataError(f"{label}必须是两个整数")
    if values[0] > values[1]:
        raise JsonDataError(f"{label}下限不能大于上限")
    return int(values[0]), int(values[1])


__all__ = ["ForgingService"]
