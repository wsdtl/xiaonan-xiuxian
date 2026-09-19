from __future__ import annotations

from collections.abc import Mapping

from game.core.asset import AssetService, InventoryAdjustment
from game.core.character import CharacterService
from game.core.data import JsonDataError, JsonDataService, nonempty_text, positive_int
from game.core.database import (
    DatabaseService,
    StateAddress,
    StateConflictError,
    StateMutation,
    TransactionCommand,
)
from game.core.item_catalog import ItemCatalogService
from game.core.location import LocationService

from .contracts import GiftError, GiftResult, GiftSendCommand

RESULT_STATE = "gift_result"
BASIC_ITEM_CATEGORIES = frozenset({"灵植", "灵矿", "兽宝"})


class GiftService:
    state_types = frozenset({RESULT_STATE})

    def __init__(self, data: JsonDataService, database: DatabaseService, location: LocationService, character: CharacterService, asset: AssetService, item_catalog: ItemCatalogService) -> None:
        self._data = data
        self._database = database
        self._location = location
        self._character = character
        self._asset = asset
        self._item_catalog = item_catalog
        self._initialized = False
        self._allowed: frozenset[str] = frozenset()
        self._maximum_quantity = 0

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("玩家赠送核心已经初始化")
        rules = self._data.dataset("交易规则").get("玩家赠送")
        if not isinstance(rules, Mapping):
            raise JsonDataError("玩法/交易/规则/玩家赠送.json 必须是对象")
        allowed = rules.get("允许物品类别")
        if not isinstance(allowed, (list, tuple)) or not allowed:
            raise JsonDataError("玩家赠送.允许物品类别不能为空")
        self._allowed = frozenset(str(value) for value in allowed)
        self._maximum_quantity = _positive_int(rules.get("单次数量上限"), "玩家赠送.单次数量上限")
        self._initialized = True

    async def resolve_target(self, user_id: str, query: str) -> str:
        candidates = await self._location.nearby_players(user_id)
        ids = tuple(value.user_id for value in candidates.values)
        query = _text(query, "赠送目标")
        if query in ids:
            return query
        profiles = await self._character.public_profiles(ids)
        matches = tuple(value.user_id for value in profiles if value.name == query)
        if not matches:
            raise GiftError("目标不在附近")
        if len(matches) > 1:
            raise GiftError("目标姓名重名，请改用用户编号")
        return matches[0]

    async def send(self, command: GiftSendCommand) -> GiftResult:
        self._require_initialized()
        sender = _text(command.user_id, "赠送者")
        target = _text(command.target_user_id, "接收者")
        request_id = _text(command.request_id, "请求编号")
        if sender == target:
            raise GiftError("不能赠送给自己")
        cached = await self._database.get(StateAddress(sender, RESULT_STATE, request_id))
        if cached is not None:
            return _result(cached.value, replayed=True)
        first, second = await self._location.current(sender), await self._location.current(target)
        if (first.space_type, first.space_id, first.xy) != (second.space_type, second.space_id, second.xy):
            raise GiftError("赠送双方必须处于同一位置")
        if command.spirit_stones < 0:
            raise GiftError("灵石数量不能为负数")
        if command.spirit_stones > 0:
            if command.item_id or command.grade_id or command.quantity:
                raise GiftError("灵石赠送不能同时填写物品参数")
            quantity = _bounded(command.spirit_stones, self._maximum_quantity, "灵石数量")
            plan = await self._character.plan_spirit_stone_change(sender, delta=-quantity)
            receive = await self._character.plan_spirit_stone_change(target, delta=quantity)
            kind, item_id, grade_id = "灵石", "", ""
            operations = (plan.operation, receive.operation)
        else:
            item = self._item_catalog.inspect(command.item_id)
            if not (
                item.category in self._allowed
                or "基础物品" in self._allowed
                and item.category in BASIC_ITEM_CATEGORIES
            ):
                raise GiftError("该物品类别不允许玩家赠送")
            grade = self._asset.grade(command.grade_id)
            quantity = _bounded(command.quantity, self._maximum_quantity, "物品数量")
            outgoing = await self._asset.plan_inventory_changes(sender, (InventoryAdjustment(item.item_id, grade.grade_id, -quantity),))
            incoming = await self._asset.plan_inventory_changes(target, (InventoryAdjustment(item.item_id, grade.grade_id, quantity),))
            kind, item_id, grade_id = item.category, item.item_id, grade.grade_id
            operations = (*outgoing.operations, *incoming.operations)
        value = {"请求编号": request_id, "赠送者": sender, "接收者": target, "类别": kind, "数量": quantity, "物品编号": item_id, "品级": grade_id}
        operations = (*operations, StateMutation(sender, RESULT_STATE, request_id, value, 0))
        try:
            receipt = await self._database.commit(TransactionCommand(sender, request_id, "玩家赠送", tuple(operations), {"接收者": target}))
        except StateConflictError as exc:
            raise GiftError("资产已经变化，请重试") from exc
        return _result(value, replayed=receipt.replayed)

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("玩家赠送核心尚未初始化")


def _result(value: Mapping[str, object], *, replayed: bool) -> GiftResult:
    return GiftResult(str(value["请求编号"]), str(value["赠送者"]), str(value["接收者"]), str(value["类别"]), int(value["数量"]), str(value.get("物品编号") or ""), str(value.get("品级") or ""), replayed)


def _bounded(value: object, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum:
        raise GiftError(f"{label}必须在1至{maximum}之间")
    return value


def _positive_int(value: object, label: str) -> int:
    return positive_int(value, label, error=GiftError)


def _text(value: object, label: str) -> str:
    return nonempty_text(value, label, error=GiftError)
