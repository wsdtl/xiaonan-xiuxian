"""铜雀台地点、修为、道契与纳戒的事务编排。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from game.core.asset import AssetService, InventoryAdjustment, InventoryChangeError
from game.core.character import CharacterCultivationError, CharacterService
from game.core.companion import CompanionCultivationError, CompanionService
from game.core.cultivation_transfer import (
    CultivationTransferError,
    CultivationTransferService,
)
from game.core.data import JsonDataError, JsonDataService
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
from game.core.location import LocationError, LocationService
from game.core.player_state import PlayerStateService
from game.core.world import LocationQuery, WorldService

from .contracts import (
    TongquetaiConflictError,
    TongquetaiError,
    TongquetaiOutcome,
    TongquetaiPreview,
    TongquetaiRequest,
    TongquetaiSettlement,
)


class TongquetaiFeature:
    """跨核心编排夺元，不持有第二份人物或道侣状态。"""

    def __init__(
        self,
        data: JsonDataService,
        transfer: CultivationTransferService,
        character: CharacterService,
        companion: CompanionService,
        asset: AssetService,
        player_state: PlayerStateService,
        location: LocationService,
        world: WorldService,
        database: DatabaseService,
        innate_treasure: InnateTreasureService,
    ) -> None:
        self._data = data
        self._transfer = transfer
        self._character = character
        self._companion = companion
        self._asset = asset
        self._player_state = player_state
        self._location = location
        self._world = world
        self._database = database
        self._innate_treasure = innate_treasure
        self._copy: Mapping[str, object] | None = None
        self._buttons: tuple[Mapping[str, object], ...] = ()

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("铜雀台玩法已经初始化")
        for ready, label in (
            (self._transfer.status().initialized, "修为转移核心"),
            (self._character.status().initialized, "角色核心"),
            (self._companion.status().initialized, "道侣核心"),
            (self._asset.status().initialized, "资产核心"),
            (self._player_state.status().initialized, "人物状态核心"),
            (self._location.status().initialized, "位置核心"),
            (self._world.status().initialized, "世界核心"),
            (self._database.status().initialized, "数据库核心"),
            (self._innate_treasure.status().initialized, "先天灵宝核心"),
        ):
            if not ready:
                raise RuntimeError(f"{label}必须先于铜雀台玩法启动")
        document = self._data.dataset("铜雀台展示").get("文本")
        if not isinstance(document, Mapping):
            raise JsonDataError("铜雀台展示缺少文本.json")
        for section in ("预览", "结算", "错误"):
            if not isinstance(document.get(section), Mapping):
                raise JsonDataError(f"铜雀台展示缺少{section}")
        buttons = document.get("按钮")
        if not isinstance(buttons, Sequence) or isinstance(buttons, (str, bytes)):
            raise JsonDataError("铜雀台展示.按钮必须是数组")
        self._buttons = tuple(_button(raw, index) for index, raw in enumerate(buttons))
        self._copy = document

    def copy(self, section: str, key: str, **values: object) -> str:
        if self._copy is None:
            raise RuntimeError("铜雀台玩法尚未初始化")
        group = self._copy.get(section)
        value = group.get(key) if isinstance(group, Mapping) else None
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"铜雀台展示缺少文本：{section}.{key}")
        return value.format_map(values)

    def actions(self, *, has_medicine: bool) -> tuple[Mapping[str, object], ...]:
        return tuple(
            button
            for button in self._buttons
            if button["条件"] == "始终"
            or (button["条件"] == "有护契丹" and has_medicine)
        )

    async def preview(self, user_id: str) -> TongquetaiPreview:
        context = await self._context(user_id)
        protected = await self._outcome(
            user_id, "护契", context["values"].protected_amount
        )
        severed = await self._outcome(
            user_id, "离契", context["values"].severed_amount
        )
        stack = await self._medicine_stack(user_id)
        return TongquetaiPreview(
            context["location"],
            context["profile"].name,
            context["instance"].companion_id,
            context["definition"].name,
            context["instance"].level,
            context["values"].cultivation,
            protected,
            severed,
            self._transfer.medicine_id,
            context["medicine_name"],
            stack is not None,
            context["treasure_activation"],
        )

    async def settle(self, request: TongquetaiRequest) -> TongquetaiSettlement:
        user_id = _text(request.user_id, "user_id")
        request_id = _text(request.request_id, "request_id")
        mode = _mode(request.mode)
        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != "铜雀台夺元":
                raise TongquetaiConflictError("请求编号已经用于其他操作")
            if committed.payload.get("模式") != mode:
                raise TongquetaiConflictError("夺元模式与已提交事务不一致")
            return _settlement(committed.payload, replayed=True)
        context = await self._context(user_id)
        offered = (
            context["values"].protected_amount
            if mode == "护契"
            else context["values"].severed_amount
        )
        absorption = await self._character.plan_absorb_experience(
            user_id, experience=offered
        )
        reset = await self._companion.plan_cultivation_reset(user_id)
        medicine_grade_name = ""
        operations = [absorption.operation, reset.operation]
        affection_before = Decimal(0)
        try:
            if mode == "护契":
                stack = await self._medicine_stack(user_id)
                if stack is None:
                    raise TongquetaiError("纳戒中没有守真定契丹")
                inventory = await self._asset.plan_inventory_changes(
                    user_id,
                    (InventoryAdjustment(stack.item_id, stack.grade.grade_id, -1),),
                )
                operations = list(inventory.operations) + operations + [reset.active_guard]
                medicine_grade_name = stack.grade.name
                relation = await self._companion.relation(
                    user_id, context["instance"].companion_id
                )
                affection_before = relation.current_affection
            else:
                severance = await self._companion.plan_severance(user_id)
                operations.extend(severance.operations)
                affection_before = severance.affection_before
            payload = {
                "地点": context["location"],
                "人物名称": context["profile"].name,
                "道侣编号": context["instance"].companion_id,
                "道侣名称": context["definition"].name,
                "道侣故地": context["definition"].location_name,
                "模式": mode,
                "应得修为": absorption.experience_offered,
                "承接修为": absorption.experience_accepted,
                "溢散修为": absorption.experience_discarded,
                "原好感": float(affection_before),
                "丹药编号": self._transfer.medicine_id if mode == "护契" else "",
                "丹药名称": context["medicine_name"] if mode == "护契" else "",
                "丹药品级": medicine_grade_name,
                "先天灵宝": _activation_payload(context["treasure_activation"]),
            }
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id,
                    request_id,
                    "铜雀台夺元",
                    tuple(operations),
                    payload,
                )
            )
        except (InventoryChangeError, CharacterCultivationError, CompanionCultivationError) as exc:
            raise TongquetaiError(str(exc)) from exc
        except StateConflictError as exc:
            raise TongquetaiConflictError("人物、道侣关系或纳戒已经变化，请重新预览") from exc
        except IdempotencyConflictError as exc:
            raise TongquetaiConflictError("请求编号已经用于其他操作") from exc
        return _settlement(payload, replayed=receipt.replayed)

    async def _context(self, user_id: str) -> dict[str, object]:
        user = _text(user_id, "user_id")
        authorization = await self._player_state.authorize(
            user, self._transfer.guard_rule
        )
        if not authorization.allowed:
            raise TongquetaiError(authorization.reason)
        try:
            current = await self._location.current(user)
            location = self._world.locate(LocationQuery(xy=current.xy))
            if self._transfer.location_function not in location.available_functions:
                raise TongquetaiError("只有身在铜雀台才能夺元")
            active = await self._companion.active_instance(user)
            activation: InnateTreasureActivation | None = None
            severed_rate = None
            treasure_effect = await self._innate_treasure.effect(user, "铜雀台夺元")
            if treasure_effect is not None:
                treasure, effect = treasure_effect
                if effect.ability == "提高转化效率":
                    severed_rate = round(float(effect.values["效率"]) * 100)
                    activation = InnateTreasureActivation(
                        treasure.treasure_id,
                        treasure.name,
                        treasure.authority,
                        f"离契转化率提高到{severed_rate}%",
                    )
            values = self._transfer.values(
                level=active.instance.level,
                experience=active.instance.experience,
                severed_rate=severed_rate,
            )
            profile = await self._character.profile(user)
        except (LocationError, CompanionCultivationError, CultivationTransferError) as exc:
            raise TongquetaiError(str(exc)) from exc
        definition = self._companion.definition(active.instance.companion_id)
        medicine = self._data.entity("丹药", self._transfer.medicine_id)
        return {
            "location": location.location_name,
            "instance": active.instance,
            "definition": definition,
            "values": values,
            "profile": profile,
            "medicine_name": _text(medicine.get("名称"), "护契丹.名称"),
            "treasure_activation": activation,
        }

    async def _outcome(self, user_id: str, mode: str, offered: int) -> TongquetaiOutcome:
        plan = await self._character.plan_absorb_experience(user_id, experience=offered)
        return TongquetaiOutcome(
            mode,
            offered,
            plan.experience_accepted,
            plan.experience_discarded,
        )

    async def _medicine_stack(self, user_id: str):
        stacks = await self._asset.inventory_stacks(user_id, self._transfer.medicine_id)
        return min(stacks, key=lambda stack: stack.grade.order) if stacks else None


def _settlement(value: Mapping[str, object], *, replayed: bool) -> TongquetaiSettlement:
    return TongquetaiSettlement(
        _text(value.get("地点"), "夺元事务.地点"),
        _text(value.get("人物名称"), "夺元事务.人物名称"),
        _text(value.get("道侣编号"), "夺元事务.道侣编号"),
        _text(value.get("道侣名称"), "夺元事务.道侣名称"),
        _text(value.get("道侣故地"), "夺元事务.道侣故地"),
        _mode(value.get("模式")),
        _nonnegative_int(value.get("应得修为"), "夺元事务.应得修为"),
        _nonnegative_int(value.get("承接修为"), "夺元事务.承接修为"),
        _nonnegative_int(value.get("溢散修为"), "夺元事务.溢散修为"),
        float(value.get("原好感") or 0),
        str(value.get("丹药编号") or ""),
        str(value.get("丹药名称") or ""),
        str(value.get("丹药品级") or ""),
        replayed,
        _payload_activation(value.get("先天灵宝")),
    )


def _activation_payload(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, InnateTreasureActivation):
        raise TongquetaiError("铜雀台灵宝快照无效")
    return {
        "编号": value.treasure_id,
        "名称": value.name,
        "权柄": value.authority,
        "结果": value.summary,
    }


def _payload_activation(value: object) -> InnateTreasureActivation | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TongquetaiError("夺元事务.先天灵宝必须是对象")
    return InnateTreasureActivation(
        _text(value.get("编号"), "夺元事务.先天灵宝.编号"),
        _text(value.get("名称"), "夺元事务.先天灵宝.名称"),
        _text(value.get("权柄"), "夺元事务.先天灵宝.权柄"),
        _text(value.get("结果"), "夺元事务.先天灵宝.结果"),
    )


def _button(value: object, index: int) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"铜雀台按钮[{index}]必须是对象")
    expected = {"编号", "名称", "命令", "条件", "行为", "样式"}
    if set(value) != expected:
        raise JsonDataError(f"铜雀台按钮[{index}]字段不完整")
    result = {key: _text(value.get(key), f"铜雀台按钮[{index}].{key}") for key in expected}
    if result["条件"] not in {"始终", "有护契丹"}:
        raise JsonDataError("铜雀台按钮条件无效")
    if result["行为"] not in {"callback", "send", "fill", "link"}:
        raise JsonDataError("铜雀台按钮行为无效")
    if result["样式"] not in {"primary", "secondary"}:
        raise JsonDataError("铜雀台按钮样式无效")
    return result


def _mode(value: object) -> str:
    result = str(value or "").strip()
    if result not in {"护契", "离契"}:
        raise TongquetaiError("夺元方式只能是护契或离契")
    return result


def _text(value: object, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise TongquetaiError(f"{label}不能为空")
    return result


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TongquetaiError(f"{label}必须是非负整数")
    return value


__all__ = ["TongquetaiFeature"]
