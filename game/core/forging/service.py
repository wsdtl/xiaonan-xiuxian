"""解释炼器 JSON，并原子完成材料消耗与器律产出。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from math import ceil
from types import MappingProxyType

from game.core.asset import (
    AssetEntry,
    AssetService,
    AssetStateError,
    InventoryAdjustment,
    InventoryChangeError,
)
from game.core.crafting import (
    CraftCostRules,
    CraftEnvironment,
    CraftFacility,
    current_environment,
    facility_from_payload,
    facility_payload,
    material_quantity,
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
    speech,
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
    WeaponAdvance,
    WeaponStage,
)
from game.core.data import (
    number,
    number as _number,
    sequence as _sequence,
    strict_text,
    strict_text as _text,
)
from game.core.promotion import MaterialRequirement

#: 器律可用器阶从数据的 `阶序` 推导（阶序 1 是凡器，不开放器律孔），代码不再另存一份。
_LAW_STAGE_FLOOR = 2


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
        self._cost_rules: CraftCostRules | None = None

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
            dict(_mapping(self._data.dataset("装备规则").get("本命武器"), "装备规则.本命武器"))
        )
        law_rule = _mapping(rules.get("器则"), "炼器规则.器则")
        rows = tuple(
            _mapping(raw, "器则.器阶[]")
            for raw in _sequence(law_rule.get("器阶"), "器则.器阶")
        )
        self._stages = tuple(_weapon_stage(row) for row in rows)
        # 器阶的阶梯（顺序与解锁范围）在 器则.json 里声明，这里只校验、不另立一份：
        # 与 品级.json 同一套做法——数据声明阶梯，代码读它。
        # **没有强度系数**：器律的强度来自它所在的解锁池（后天灵宝池的内容本身就更强），
        # 设计上刻意不引入品阶/倍率，所以这里只校验顺序与解锁范围。
        orders = tuple(_positive_int(row.get("阶序"), "器则.器阶[].阶序") for row in rows)
        if orders != tuple(range(1, len(rows) + 1)):
            raise JsonDataError("器阶阶序必须是 1..N 且与数组顺序一致")
        self._law_stages = tuple(
            stage.name for stage, order in zip(self._stages, orders)
            if order >= _LAW_STAGE_FLOOR
        )
        self._stage_by_name = MappingProxyType(
            {stage.name: stage for stage in self._stages}
        )
        self._laws = MappingProxyType(self._load_laws())
        self._law_by_name = MappingProxyType(
            {law.name: law_id for law_id, law in self._laws.items()}
        )
        self._cost_rules = CraftCostRules(self._data)
        self._validate_static_rules(law_rule)
        self._initialized = True
        return self.status()

    def status(self) -> ForgingStatus:
        return ForgingStatus(
            self._initialized,
            len(self._laws),
            self._world.facility_count(),
            len(_item_ids(self._data, "兽宝")),
            len(_item_ids(self._data, "灵矿")),
            int(self._weapon_rule.get("等级上限") or 0),
        )

    def law_name(self, identifier: str) -> str:
        """给升阶方案显示用：按编号或名称取器律正式名。"""

        self._require_initialized()
        return self._resolve_law(identifier).name

    def requirements(self, identifier: str, quantity: int = 1) -> tuple[MaterialRequirement, ...]:
        """把一件器律的材料表按数量展开成升阶要求。"""

        self._require_initialized()
        count = _positive_int(quantity, "炼制数量")
        law = self._resolve_law(identifier)
        result: list[MaterialRequirement] = []
        for raw in law.materials:
            category = _text(raw.get("类别"), f"{law.name}.材料.类别")
            item_id = str(raw.get("编号") or "")
            need = _positive_int(raw.get("数量"), f"{law.name}.材料.数量") * count
            minimum = self._asset.grade(str(raw.get("最低品级") or "黄品"))
            result.append(
                MaterialRequirement(category, item_id, need, minimum.grade_id)
            )
        return tuple(result)

    def laws(self, stage: str) -> tuple[ForgingLaw, ...]:
        self._require_initialized()
        normalized = str(stage or "").strip()
        if normalized not in self._law_stages:
            raise ForgingError(f"未知器律器阶：{normalized or '<空>'}")
        return tuple(
            sorted(
                (law for law in self._laws.values() if law.stage == normalized),
                key=lambda value: value.law_id,
            )
        )

    def assess(
        self,
        identifier: str,
        entries: tuple[AssetEntry, ...],
        facility: CraftFacility | None = None,
        quantity: int = 1,
    ) -> ForgingAssessment:
        self._require_initialized()
        law = self._resolve_law(identifier)
        if law.materials:
            return self._assess_materials(law, entries, facility, quantity)
        raise ForgingError("器律缺少材料表")

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
        environment = await self._environment(normalized)
        return ForgingOverview(
            normalized,
            environment.location_name,
            environment.facility,
            tuple(
                (stage, sum(law.stage == stage for law in self._laws.values()))
                for stage in self._law_stages
            ),
        )

    async def list_laws(self, user_id: str, stage: str) -> ForgingLawList:
        normalized = _request_text(user_id, "user_id")
        normalized_stage = str(stage or "").strip()
        if normalized_stage not in self._law_stages:
            raise ForgingError(f"未知器律器阶：{normalized_stage or '<空>'}")
        environment = await self._environment(normalized)
        entries = await self._material_entries(normalized)
        stones = await self._asset.spirit_stone_balance(normalized)
        laws = sorted(
            (law for law in self._laws.values() if law.stage == normalized_stage),
            key=lambda law: law.law_id,
        )
        return ForgingLawList(
            normalized,
            environment.location_name,
            environment.facility,
            normalized_stage,
            tuple(
                ForgingLawEntry(
                    law,
                    (
                        preview := self._build_preview(
                            normalized, environment, law, entries, stones=stones
                        )
                    ).can_forge,
                    sum(missing.quantity for missing in preview.missing_materials),
                )
                for law in laws
            ),
        )

    async def preview(
        self, user_id: str, identifier: str, quantity: int = 1
    ) -> ForgingPreview:
        normalized = _request_text(user_id, "user_id")
        count = _positive_int(quantity, "炼制数量")
        law = self._resolve_law(identifier)
        environment = await self._environment(normalized)
        entries = await self._material_entries(normalized)
        stones = await self._asset.spirit_stone_balance(normalized)
        return self._build_preview(
            normalized, environment, law, entries, quantity=count, stones=stones
        )

    async def forge(
        self, user_id: str, request_id: str, identifier: str, quantity: int = 1
    ) -> ForgingResult:
        normalized = _request_text(user_id, "user_id")
        request = _request_text(request_id, "request_id")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise ForgingError("炼制数量必须是正整数")
        law = self._resolve_law(identifier)
        committed = await self._database.committed_transaction(normalized, request)
        if committed is not None:
            if (
                committed.receipt.business_type != "炼器"
                or committed.payload.get("器律编号") != law.law_id
            ):
                raise ForgingConflictError("请求编号已经用于其他操作")
            return self._replayed_result(normalized, law, committed.payload)
        preview = await self.preview(normalized, law.law_id, quantity)
        if not preview.can_forge:
            raise ForgingMaterialError("纳戒中的兽宝、灵矿或灵石不足以炼成该器律")
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
                normalized, preview.law.law_id, quantity
            )
            stones = await self._asset.plan_spirit_stone_change(
                normalized, -preview.spirit_stone_cost
            )
            payload = {
                "地点": preview.location_name,
                "设施": facility_payload(preview.facility),
                "炼器数量": quantity,
                "灵石消耗": preview.spirit_stone_cost,
                "器律编号": preview.law.law_id,
                "器藏原数量": reserve.quantity_before,
                "器藏现数量": reserve.quantity_after,
                "兽宝": [_material_payload(item) for item in preview.beast_materials],
                "灵矿": [_material_payload(item) for item in preview.mineral_materials],
                "先天灵宝": activation_payload(activation),
            }
            receipt = await self._database.commit(
                TransactionCommand(
                    normalized,
                    request,
                    "炼器",
                    inventory.operations + stones.operations + (reserve.operation,),
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
            facility = facility_from_payload(payload.get("设施"), "炼器事务.设施")
            quantity = _payload_positive_int(
                payload.get("炼器数量"), "炼器事务.炼器数量"
            )
            stone_cost = _payload_nonnegative_int(
                payload.get("灵石消耗"), "炼器事务.灵石消耗"
            )
            beasts = _payload_materials(
                payload.get("兽宝"), self._asset, self._data, "兽宝"
            )
            minerals = _payload_materials(
                payload.get("灵矿"), self._asset, self._data, "灵矿"
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
        preview = ForgingPreview(
            user_id,
            location_name,
            facility,
            law,
            beasts,
            minerals,
            (),
            True,
            quantity,
            stone_cost,
        )
        return ForgingResult(preview, before, after, True, activation)

    def _build_preview(
        self,
        user_id: str,
        environment: CraftEnvironment,
        law: ForgingLaw,
        entries: tuple[AssetEntry, ...],
        *,
        quantity: int = 1,
        stones: int = 0,
    ) -> ForgingPreview:
        value = self.assess(law.law_id, entries, environment.facility, quantity)
        unit_cost = self._cost_rules.cost("炼器", law.stage) if self._cost_rules else 0
        cost = unit_cost * quantity
        return ForgingPreview(
            user_id,
            environment.location_name,
            environment.facility,
            value.law,
            value.beast_materials,
            value.mineral_materials,
            value.missing_materials,
            value.can_forge and stones >= cost,
            quantity,
            cost,
        )

    def _assess_materials(
        self,
        law: ForgingLaw,
        entries: tuple[AssetEntry, ...],
        facility: CraftFacility | None = None,
        quantity: int = 1,
    ) -> ForgingAssessment:
        beasts: list[ForgingMaterial] = []
        minerals: list[ForgingMaterial] = []
        missing: list[ForgingMissingMaterial] = []
        for raw in law.materials:
            category = _text(raw.get("类别"), f"{law.name}.材料.类别")
            item_id = str(raw.get("编号") or "")
            need = _positive_int(raw.get("数量"), f"{law.name}.材料.数量") * quantity
            if facility is not None:
                need = material_quantity(need, facility.material_saving_bp)
            minimum = self._asset.grade(str(raw.get("最低品级") or "黄品"))
            candidates = sorted(
                (
                    entry
                    for entry in entries
                    if entry.subcategory == category
                    and (not item_id or entry.content_id == item_id)
                    and self._asset.grade(entry.grade_id).order >= minimum.order
                ),
                key=lambda entry: (
                    self._asset.grade(entry.grade_id).order,
                    entry.content_id,
                    entry.instance_key,
                ),
            )
            target = beasts if category == "兽宝" else minerals
            for entry in candidates:
                if need <= 0:
                    break
                take = min(need, entry.quantity)
                target.append(
                    ForgingMaterial(
                        entry.content_id,
                        entry.name,
                        entry.grade_id,
                        entry.grade_name,
                        category,
                        "指定" if item_id else "同类",
                        take,
                    )
                )
                need -= take
            if need > 0:
                missing.append(
                    ForgingMissingMaterial(
                        category,
                        f"{minimum.name}及以上{category}" + (f"（{item_id}）" if item_id else ""),
                        need,
                    )
                )
        return ForgingAssessment(
            law, tuple(beasts), tuple(minerals), tuple(missing), not missing
        )

    async def _material_entries(self, user_id: str) -> tuple[AssetEntry, ...]:
        snapshot = await self._asset.snapshot(user_id)
        return tuple(
            entry
            for entry in snapshot.entries
            if entry.category == "基础物品" and entry.subcategory in {"兽宝", "灵矿"}
        )

    async def _environment(self, user_id: str) -> CraftEnvironment:
        self._require_initialized()
        return await current_environment(
            self._location, self._world, user_id, "炼器"
        )

    def _resolve_law(self, identifier: str) -> ForgingLaw:
        self._require_initialized()
        query = str(identifier or "").strip()
        law = self._laws.get(query)
        if law is None:
            law = self._laws.get(self._law_by_name.get(query, ""))
        if law is None:
            raise ForgingError(f"未找到唯一器律：{query or '<空>'}")
        return law

    def _load_laws(self) -> dict[str, ForgingLaw]:
        result: dict[str, ForgingLaw] = {}
        names: set[str] = set()
        for law_id, raw in self._data.entities("器律").items():
            name = _text(raw.get("名称"), f"器律 {law_id}.名称")
            if name in names:
                raise JsonDataError(f"器律名称重复：{name}")
            names.add(name)
            stage = _text(raw.get("器阶"), f"器律 {law_id}.器阶")
            materials = tuple(
                _mapping(item, f"器律 {name}.材料[]")
                for item in _sequence(raw.get("材料", ()), f"器律 {name}.材料")
            )
            if not materials:
                raise JsonDataError(f"器律 {name} 缺少材料表")
            result[law_id] = ForgingLaw(law_id, name, stage, materials)
        return result

    def _validate_static_rules(self, law_rule: Mapping[str, object]) -> None:
        maximum = _positive_int(self._weapon_rule.get("等级上限"), "本命武器.等级上限")
        if maximum != 100:
            raise JsonDataError("当前本命武器等级上限必须为100")
        if not self._stages or self._stages[0].name != "凡器":
            raise JsonDataError("器阶第一位必须是凡器（凡器不开放器律孔）")
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


def _material_payload(material: ForgingMaterial) -> dict[str, object]:
    return {
        "编号": material.item_id,
        "品级": material.grade_id,
        "数量": material.quantity,
        "类别": material.trait,
        "关系": material.relation,
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
    asset: AssetService,
    data: JsonDataService,
    label: str,
) -> tuple[ForgingMaterial, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"炼器事务.{label}必须是数组")
    result: list[ForgingMaterial] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise TypeError(f"炼器事务.{label}材料必须是对象")
        item_id = _payload_text(raw.get("编号"), f"炼器事务.{label}.编号")
        grade = asset.grade(_payload_text(raw.get("品级"), f"炼器事务.{label}.品级"))
        category = str(raw.get("类别") or "").strip()
        if not category:
            # 旧回执没有“类别”，但物品编号仍能确定类别；不因此让重放失败。
            category = data.entity_record("基础物品", item_id).number_category
        result.append(
            ForgingMaterial(
                item_id,
                _entity_name(data, item_id),
                grade.grade_id,
                grade.name,
                category,
                _payload_text(raw.get("关系"), f"炼器事务.{label}.关系"),
                _payload_positive_int(raw.get("数量"), f"炼器事务.{label}.数量"),
            )
        )
    return tuple(result)


def _payload_text(value: object, label: str) -> str:
    return strict_text(value, label, error=ValueError)


def _payload_positive_int(value: object, label: str) -> int:
    return positive_int(value, label, error=ValueError)


def _payload_nonnegative_int(value: object, label: str) -> int:
    return nonnegative_int(value, label, error=ValueError)


def _weapon_stage(value: Mapping[str, object]) -> WeaponStage:
    bounds = _integer_pair(value.get("等级范围"), "器阶.等级范围")
    minerals = _integer_pair(value.get("矿材份数"), "器阶.矿材份数")
    return WeaponStage(
        _text(value.get("名称"), "器阶.名称"),
        bounds[0],
        bounds[1],
        _nonnegative_int(value.get("开放器律孔"), "器阶.开放器律孔"),
        minerals,
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


def _texts(value: object, label: str) -> tuple[str, ...]:
    return tuple(_text(raw, label) for raw in _sequence(value, label))




def _request_text(value: object, label: str) -> str:
    return nonempty_text(value, label, error=ForgingError)


def _request_number(value: object, label: str) -> float:
    return number(value, label, error=ForgingError)


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
