"""编排共享纳戒扣减与人物、道侣服丹状态变更。"""

from __future__ import annotations

from collections.abc import Mapping

from game.core.asset import AssetService, AssetStateError, InventoryAdjustment
from game.core.character import CharacterCultivationError, CharacterService
from game.core.companion import CompanionCultivationError, CompanionService
from game.core.data import JsonDataError, JsonDataService, nonempty_text
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
from game.core.medicine import MedicineError, MedicineService, PreparedBattleMedicine
from game.core.player_state import PlayerStateService

from .contracts import (
    AutoMedicineRequest,
    AutoMedicineResult,
    MedicineFeatureConflictError,
    MedicineFeatureError,
    MedicineUseRequest,
    MedicineUseResult,
)


class MedicineFeature:
    """只编排正式核心服务，不拥有角色或物品状态。"""

    def __init__(
        self,
        data: JsonDataService,
        medicine: MedicineService,
        character: CharacterService,
        companion: CompanionService,
        asset: AssetService,
        player_state: PlayerStateService,
        database: DatabaseService,
        innate_treasure: InnateTreasureService,
    ) -> None:
        self._data = data
        self._medicine = medicine
        self._character = character
        self._companion = companion
        self._asset = asset
        self._player_state = player_state
        self._database = database
        self._innate_treasure = innate_treasure
        self._copy: Mapping[str, object] | None = None

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("服丹玩法已经初始化")
        for ready, label in (
            (self._medicine.status().initialized, "丹药核心"),
            (self._character.status().initialized, "角色核心"),
            (self._companion.status().initialized, "道侣核心"),
            (self._asset.status().initialized, "资产核心"),
            (self._player_state.status().initialized, "人物状态核心"),
            (self._database.status().initialized, "数据库核心"),
            (self._innate_treasure.status().initialized, "先天灵宝核心"),
        ):
            if not ready:
                raise RuntimeError(f"{label}必须先于服丹玩法启动")
        copy = self._data.dataset("服丹展示").get("文本")
        if not isinstance(copy, Mapping):
            raise JsonDataError("服丹展示缺少文本.json")
        for section in ("服丹", "自动用药", "错误"):
            if not isinstance(copy.get(section), Mapping):
                raise JsonDataError(f"服丹展示缺少文本.{section}")
        self._copy = copy

    def copy(self, section: str, key: str, **values: object) -> str:
        if self._copy is None:
            raise RuntimeError("服丹玩法尚未初始化")
        group = self._copy.get(section)
        value = group.get(key) if isinstance(group, Mapping) else None
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"服丹展示缺少文本：{section}.{key}")
        return value.format_map(values)

    async def use(self, request: MedicineUseRequest) -> MedicineUseResult:
        target = _target(request.target)
        user_id = _text(request.user_id, "user_id")
        request_id = _text(request.request_id, "request_id")
        query = _text(request.medicine, "丹药编号或名称")
        requested_grade = str(request.grade or "").strip()
        try:
            medicine_id = self._medicine.resolve(query)
        except MedicineError as exc:
            raise MedicineFeatureError(str(exc)) from exc
        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != "服丹":
                raise MedicineFeatureConflictError("请求编号已经用于其他操作")
            return self._replayed_use(
                target, query, requested_grade, committed.payload
            )
        await self._authorize(user_id, self._medicine.active_guard_rule)
        stack = await self._inventory_stack(user_id, medicine_id, requested_grade)
        try:
            inventory = await self._asset.plan_inventory_changes(
                user_id,
                (InventoryAdjustment(medicine_id, stack.grade.grade_id, -1),),
            )
            if self._medicine.is_recovery(medicine_id):
                definition = self._medicine.recovery(
                    medicine_id, stack.grade.grade_id
                )
                activation: InnateTreasureActivation | None = None
                recovery_percent = definition.recovery_percent
                if target == "人物":
                    treasure_effect = await self._innate_treasure.effect(
                        user_id, "恢复丹生效"
                    )
                    if treasure_effect is not None:
                        treasure, effect_value = treasure_effect
                        if effect_value.ability == "提高恢复量":
                            ratio = float(effect_value.values["比例"])
                            recovery_percent *= 1 + ratio
                            activation = InnateTreasureActivation(
                                treasure.treasure_id,
                                treasure.name,
                                treasure.authority,
                                f"恢复量提高{ratio:.0%}",
                            )
                    profile = await self._character.profile(user_id)
                    plan = await self._character.plan_recovery(
                        user_id,
                        resource=definition.resource,
                        recovery_percent=recovery_percent,
                    )
                    operations = inventory.operations + (plan.operation,)
                    target_name = profile.name
                else:
                    current = await self._companion.active_instance(user_id)
                    plan = await self._companion.plan_recovery(
                        user_id,
                        resource=definition.resource,
                        recovery_percent=definition.recovery_percent,
                    )
                    operations = inventory.operations + plan.operations
                    target_name = self._companion.definition(
                        current.instance.companion_id
                    ).name
                effect = "恢复"
                resource = plan.resource
                before, after, recovered = plan.before, plan.after, plan.recovered
            elif self._medicine.is_battle(medicine_id):
                activation = None
                definition = self._medicine.battle(medicine_id, stack.grade.grade_id)
                prepared = PreparedBattleMedicine(
                    definition.medicine_id, definition.grade_id
                )
                if target == "人物":
                    profile = await self._character.profile(user_id)
                    plan = await self._character.plan_battle_medicine(
                        user_id, medicine=prepared, require_empty=True
                    )
                    operations = inventory.operations + (plan.operation,)
                    target_name = profile.name
                else:
                    current = await self._companion.active_instance(user_id)
                    plan = await self._companion.plan_battle_medicine(
                        user_id, medicine=prepared, require_empty=True
                    )
                    operations = inventory.operations + plan.operations
                    target_name = self._companion.definition(
                        current.instance.companion_id
                    ).name
                effect, resource = "寄存战丹", ""
                before = after = recovered = 0.0
            else:
                raise MedicineFeatureError("该丹药必须通过对应的专属功能使用")
            payload = {
                "目标": target,
                "目标名称": target_name,
                "请求丹药": query,
                "请求品级": requested_grade,
                "丹药编号": definition.medicine_id,
                "丹药名称": definition.name,
                "品级": definition.grade_id,
                "品级名称": definition.grade_name,
                "效果": effect,
                "资源": resource,
                "变化前": before,
                "变化后": after,
                "实际恢复": recovered,
                "先天灵宝": _activation_payload(activation),
            }
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id, request_id, "服丹", tuple(operations), payload
                )
            )
        except StateConflictError as exc:
            raise MedicineFeatureConflictError("角色或纳戒已经变化，请重试") from exc
        except IdempotencyConflictError as exc:
            raise MedicineFeatureConflictError("请求编号已经用于其他操作") from exc
        except (
            AssetStateError,
            CharacterCultivationError,
            CompanionCultivationError,
            MedicineError,
        ) as exc:
            raise MedicineFeatureError(str(exc)) from exc
        return _use_result(payload, replayed=receipt.replayed)

    async def set_automatic(
        self, request: AutoMedicineRequest
    ) -> AutoMedicineResult:
        target = _target(request.target)
        user_id = _text(request.user_id, "user_id")
        request_id = _text(request.request_id, "request_id")
        if not isinstance(request.enabled, bool):
            raise MedicineFeatureError("自动用药开关必须是开或关")
        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != "设置自动用药":
                raise MedicineFeatureConflictError("请求编号已经用于其他操作")
            return self._replayed_setting(target, request.enabled, committed.payload)
        await self._authorize(user_id, self._medicine.setting_guard_rule)
        try:
            if target == "人物":
                profile = await self._character.profile(user_id)
                plan = await self._character.plan_medicine_setting(
                    user_id, enabled=request.enabled
                )
                target_name = profile.name
                operations = (plan.operation,)
            else:
                current = await self._companion.active_instance(user_id)
                plan = await self._companion.plan_medicine_setting(
                    user_id, enabled=request.enabled
                )
                target_name = self._companion.definition(
                    current.instance.companion_id
                ).name
                operations = plan.operations
            payload = {
                "目标": target,
                "目标名称": target_name,
                "开启": request.enabled,
            }
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id,
                    request_id,
                    "设置自动用药",
                    tuple(operations),
                    payload,
                )
            )
        except StateConflictError as exc:
            raise MedicineFeatureConflictError("角色状态已经变化，请重试") from exc
        except IdempotencyConflictError as exc:
            raise MedicineFeatureConflictError("请求编号已经用于其他操作") from exc
        except (CharacterCultivationError, CompanionCultivationError) as exc:
            raise MedicineFeatureError(str(exc)) from exc
        return AutoMedicineResult(target, target_name, request.enabled, receipt.replayed)

    async def _authorize(self, user_id: str, rule_name: str) -> None:
        result = await self._player_state.authorize(user_id, rule_name)
        if not result.allowed:
            raise MedicineFeatureError(result.reason)

    async def _inventory_stack(
        self, user_id: str, medicine_id: str, grade: str
    ):
        stacks = await self._asset.inventory_stacks(user_id, medicine_id)
        if grade:
            try:
                grade_id = self._asset.grade(grade).grade_id
            except AssetStateError as exc:
                raise MedicineFeatureError(str(exc)) from exc
            stacks = tuple(stack for stack in stacks if stack.grade.grade_id == grade_id)
        if not stacks:
            suffix = f" {grade}" if grade else ""
            raise MedicineFeatureError(f"纳戒中没有该丹药{suffix}")
        return min(stacks, key=lambda value: value.grade.order)

    def _replayed_use(
        self,
        target: str,
        medicine: str,
        grade: str,
        payload: Mapping[str, object],
    ) -> MedicineUseResult:
        if (
            _text(payload.get("目标"), "服丹事务.目标") != target
            or _text(payload.get("请求丹药"), "服丹事务.请求丹药") != medicine
            or str(payload.get("请求品级") or "").strip() != grade
        ):
            raise MedicineFeatureConflictError("服丹请求与已提交事务不一致")
        return _use_result(payload, replayed=True)

    @staticmethod
    def _replayed_setting(
        target: str, enabled: bool, payload: Mapping[str, object]
    ) -> AutoMedicineResult:
        if (
            _text(payload.get("目标"), "自动用药事务.目标") != target
            or payload.get("开启") is not enabled
        ):
            raise MedicineFeatureConflictError("自动用药请求与已提交事务不一致")
        return AutoMedicineResult(
            target,
            _text(payload.get("目标名称"), "自动用药事务.目标名称"),
            enabled,
            True,
        )


def _use_result(value: Mapping[str, object], *, replayed: bool) -> MedicineUseResult:
    return MedicineUseResult(
        _text(value.get("目标"), "服丹事务.目标"),
        _text(value.get("目标名称"), "服丹事务.目标名称"),
        _text(value.get("丹药编号"), "服丹事务.丹药编号"),
        _text(value.get("丹药名称"), "服丹事务.丹药名称"),
        _text(value.get("品级"), "服丹事务.品级"),
        _text(value.get("品级名称"), "服丹事务.品级名称"),
        _text(value.get("效果"), "服丹事务.效果"),
        str(value.get("资源") or ""),
        _number(value.get("变化前"), "服丹事务.变化前"),
        _number(value.get("变化后"), "服丹事务.变化后"),
        _number(value.get("实际恢复"), "服丹事务.实际恢复"),
        replayed,
        _payload_activation(value.get("先天灵宝")),
    )


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
    if not isinstance(value, Mapping):
        raise MedicineFeatureError("服丹事务.先天灵宝必须是对象")
    return InnateTreasureActivation(
        _text(value.get("编号"), "服丹事务.先天灵宝.编号"),
        _text(value.get("名称"), "服丹事务.先天灵宝.名称"),
        _text(value.get("权柄"), "服丹事务.先天灵宝.权柄"),
        _text(value.get("结果"), "服丹事务.先天灵宝.结果"),
    )


def _target(value: object) -> str:
    result = str(value or "").strip()
    if result not in {"人物", "道侣"}:
        raise MedicineFeatureError("服丹目标只能是人物或道侣")
    return result


def _text(value: object, label: str) -> str:
    return nonempty_text(value, label, error=MedicineFeatureError)


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MedicineFeatureError(f"{label}必须是数值")
    return float(value)


__all__ = ["MedicineFeature"]
