"""固定地点货架与修行资粮购买事务。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import ceil

from game.core.asset import AssetService, AssetStateError
from game.core.character import CharacterCultivationError, CharacterService
from game.core.data import (
    JsonDataError,
    JsonDataService,
    mapping as _mapping,
    nonempty_text,
    nonnegative_int as _nonnegative_int,
    positive_int as _positive_int,
)
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    StateConflictError,
    TransactionCommand,
)
from game.core.location import LocationService
from game.core.world import LocationQuery, WorldService

from .contracts import (
    TradeCategorySummary,
    TradeConflictError,
    TradeError,
    TradeOverview,
    TradePage,
    TradeProduct,
    TradePurchaseCommand,
    TradePurchaseResult,
    TradeStatus,
)


@dataclass(frozen=True)
class _Store:
    location_name: str
    grade_ids: tuple[str, ...]
    catalogs: Mapping[str, tuple[str, ...]]


class TradeService:
    """解释地点货架，并原子交换人物灵石与修行资粮。"""


    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService,
        world: WorldService,
        location: LocationService,
        character: CharacterService,
        asset: AssetService,
    ) -> None:
        self._data = data
        self._database = database
        self._world = world
        self._location = location
        self._character = character
        self._asset = asset
        self._initialized = False
        self._stores: dict[str, _Store] = {}
        self._base_prices: dict[str, int] = {}
        self._maximum_quantity = 0
        self._page_size = 0

    def initialize(self) -> TradeStatus:
        if self._initialized:
            raise RuntimeError("地点交易核心已经初始化")
        for ready, label in (
            (self._data.status().loaded, "JSON数据"),
            (self._database.status().initialized, "数据库核心"),
            (self._world.status().initialized, "世界核心"),
            (self._location.status().initialized, "位置核心"),
            (self._character.status().initialized, "角色核心"),
            (self._asset.status().initialized, "资产核心"),
        ):
            if not ready:
                raise RuntimeError(f"{label}必须先于地点交易核心启动")
        raw = self._data.dataset("交易规则").get("修行资粮")
        rules = _mapping(raw, "玩法/交易/规则/修行资粮.json")
        if rules.get("货币") != "灵石" or rules.get("固定货架") is not True:
            raise JsonDataError("修行资粮交易必须使用灵石固定货架")
        if rules.get("公共库存") != "无限":
            raise JsonDataError("当前地点商店只支持无限公共库存")
        allowed = _strings(rules.get("允许类别"), "交易.允许类别")
        if allowed != ("真意", "气机"):
            raise JsonDataError("修行资粮交易类别必须依次为真意、气机")
        base_prices = _mapping(rules.get("类别基础价格"), "交易.类别基础价格")
        self._base_prices = {
            category: _positive_int(base_prices.get(category), f"{category}基础价格")
            for category in allowed
        }
        self._maximum_quantity = _positive_int(
            rules.get("购买数量上限"), "交易.购买数量上限"
        )
        self._page_size = _positive_int(rules.get("每页上限"), "交易.每页上限")
        if self._page_size > 50:
            raise JsonDataError("交易每页上限不能超过50")
        shops = self._data.entities("地点商店")
        for file_id, value in shops.items():
            if not file_id.endswith("商店"):
                raise JsonDataError(f"地点商店文件名必须以商店结尾：{file_id}")
            location_name = file_id.removesuffix("商店")
            row = _mapping(value, f"地点商店.{file_id}")
            unknown = set(row) - {"品级", "真意目录", "气机目录"}
            if unknown:
                raise JsonDataError(
                    f"地点商店 {location_name} 存在未知字段：{'、'.join(sorted(unknown))}"
                )
            grade_ids = _strings(row.get("品级"), f"{location_name}.品级")
            for grade_id in grade_ids:
                self._asset.grade(grade_id)
            catalogs = _catalogs(row, self._data, f"地点商店.{location_name}")
            self._stores[location_name] = _Store(location_name, grade_ids, catalogs)
        trading_locations = {
            value.name
            for value in self._world.map_view().locations
            if "交易" in value.available_functions
        }
        if trading_locations != set(self._stores):
            missing = sorted(trading_locations - set(self._stores))
            extra = sorted(set(self._stores) - trading_locations)
            raise JsonDataError(
                f"交易地点与商店文件不一致：缺少{missing or '无'}，多余{extra or '无'}"
            )
        self._initialized = True
        return self.status()

    def status(self) -> TradeStatus:
        return TradeStatus(
            self._initialized,
            len(self._stores),
            self._maximum_quantity,
        )

    async def overview(self, user_id: str) -> TradeOverview:
        store = await self._current_store(user_id)
        profile = await self._character.profile(user_id)
        return TradeOverview(
            store.location_name,
            profile.spirit_stones,
            tuple(
                TradeCategorySummary(category, len(self._products(store, category)))
                for category in ("真意", "气机")
            ),
        )

    async def page(self, user_id: str, category: str, page: int = 1) -> TradePage:
        normalized_category = str(category or "").strip()
        if normalized_category not in {"真意", "气机"}:
            raise TradeError("交易类别只能是真意或气机")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise TradeError("交易页码必须是正整数")
        store = await self._current_store(user_id)
        products = self._products(store, normalized_category)
        total_pages = max(1, ceil(len(products) / self._page_size))
        current_page = min(page, total_pages)
        start = (current_page - 1) * self._page_size
        return TradePage(
            store.location_name,
            normalized_category,
            current_page,
            total_pages,
            len(products),
            products[start : start + self._page_size],
        )

    async def purchase(self, command: TradePurchaseCommand) -> TradePurchaseResult:
        user_id = _text(command.user_id, "user_id")
        request_id = _text(command.request_id, "request_id")
        identifier = _text(command.identifier, "购买内容")
        if (
            isinstance(command.quantity, bool)
            or not isinstance(command.quantity, int)
            or not 1 <= command.quantity <= self._maximum_quantity
        ):
            raise TradeError(f"单次购买数量必须在1到{self._maximum_quantity}之间")
        try:
            grade_id = self._asset.grade(command.grade_id).grade_id
        except AssetStateError as exc:
            raise TradeError(str(exc)) from exc
        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != "购买修行资粮":
                raise TradeConflictError("请求编号已经用于其他操作")
            return self._replayed_result(
                identifier,
                grade_id,
                command.quantity,
                committed.payload,
            )
        store = await self._current_store(user_id)
        matches = tuple(
            product
            for category in ("真意", "气机")
            for product in self._products(store, category)
            if product.grade_id == grade_id
            and (product.content_id == identifier or product.name == identifier)
        )
        if len(matches) != 1:
            raise TradeError(f"当前货架未找到唯一商品：{identifier} {grade_id}")
        product = matches[0]
        total_price = product.unit_price * command.quantity
        try:
            currency = await self._character.plan_spirit_stone_change(
                user_id, delta=-total_price
            )
            reserve = await self._asset.plan_cultivation_reserve_change(
                user_id,
                category=product.category,
                content_id=product.content_id,
                grade_id=product.grade_id,
                quantity_delta=command.quantity,
            )
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id,
                    request_id,
                    "购买修行资粮",
                    (currency.operation, reserve.operation),
                    {
                        "地点": store.location_name,
                        "请求标识": identifier,
                        "请求品级": grade_id,
                        "类别": product.category,
                        "编号": product.content_id,
                        "品级": product.grade_id,
                        "数量": command.quantity,
                        "单价": product.unit_price,
                        "总价": total_price,
                        "剩余灵石": currency.after,
                        "现有储备": reserve.quantity_after,
                    },
                )
            )
        except StateConflictError as exc:
            raise TradeConflictError("人物灵石或修行资粮已经变化，请重试") from exc
        except IdempotencyConflictError as exc:
            raise TradeConflictError("请求编号已经用于其他操作") from exc
        except (AssetStateError, CharacterCultivationError) as exc:
            raise TradeError(str(exc)) from exc
        return TradePurchaseResult(
            store.location_name,
            product,
            command.quantity,
            total_price,
            currency.after,
            reserve.quantity_after,
            receipt.replayed,
        )

    def _replayed_result(
        self,
        identifier: str,
        grade_id: str,
        quantity: int,
        payload: Mapping[str, object],
    ) -> TradePurchaseResult:
        try:
            if (
                _text(payload.get("请求标识"), "交易事务.请求标识") != identifier
                or _text(payload.get("请求品级"), "交易事务.请求品级")
                != grade_id
                or _positive_int(payload.get("数量"), "交易事务.数量") != quantity
            ):
                raise ValueError("交易请求与已提交事务不一致")
            location_name = _text(payload.get("地点"), "交易事务.地点")
            category = _text(payload.get("类别"), "交易事务.类别")
            if category not in {"真意", "气机"}:
                raise ValueError("交易事务类别无效")
            content_id = _text(payload.get("编号"), "交易事务.编号")
            stored_grade = self._asset.grade(
                _text(payload.get("品级"), "交易事务.品级")
            )
            if stored_grade.grade_id != grade_id:
                raise ValueError("交易事务品级不一致")
            name = _text(
                self._data.entity(category, content_id).get("名称"),
                "交易事务.商品名称",
            )
            unit_price = _positive_int(payload.get("单价"), "交易事务.单价")
            total_price = _positive_int(payload.get("总价"), "交易事务.总价")
            if total_price != unit_price * quantity:
                raise ValueError("交易事务总价不一致")
            spirit_stones_after = _nonnegative_int(
                payload.get("剩余灵石"), "交易事务.剩余灵石"
            )
            reserve_after = _positive_int(
                payload.get("现有储备"), "交易事务.现有储备"
            )
        except (AssetStateError, JsonDataError, TradeError, TypeError, ValueError) as exc:
            raise TradeConflictError("已提交交易事务无法还原") from exc
        return TradePurchaseResult(
            location_name,
            TradeProduct(
                category,
                content_id,
                name,
                stored_grade.grade_id,
                stored_grade.name,
                unit_price,
            ),
            quantity,
            total_price,
            spirit_stones_after,
            reserve_after,
            True,
        )

    async def _current_store(self, user_id: str) -> _Store:
        self._require_initialized()
        current = await self._location.current(_text(user_id, "user_id"))
        location = self._world.locate(LocationQuery(xy=current.xy))
        if not location.location_name or "交易" not in location.available_functions:
            raise TradeError("当前位置没有交易功能")
        try:
            return self._stores[location.location_name]
        except KeyError as exc:
            raise TradeError("当前位置缺少正式商店货架") from exc

    def _products(self, store: _Store, category: str) -> tuple[TradeProduct, ...]:
        result: list[TradeProduct] = []
        seen: set[tuple[str, str]] = set()
        for file_id in store.catalogs[category]:
            for content_id in self._data.pool_members((file_id,), category):
                raw = self._data.entity(category, content_id)
                name = _text(raw.get("名称"), f"{category}.{content_id}.名称")
                for grade_id in store.grade_ids:
                    key = (content_id, grade_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    grade = self._asset.grade(grade_id)
                    price = int(self._base_prices[category] * grade.price_multiplier)
                    result.append(
                        TradeProduct(
                            category,
                            content_id,
                            name,
                            grade.grade_id,
                            grade.name,
                            price,
                        )
                    )
        return tuple(
            sorted(result, key=lambda value: (value.content_id, value.grade_id))
        )

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("地点交易核心尚未初始化")


def _catalogs(
    value: object, data: JsonDataService, label: str
) -> Mapping[str, tuple[str, ...]]:
    row = _mapping(value, label)
    result: dict[str, tuple[str, ...]] = {}
    for category in ("真意", "气机"):
        catalogs = _strings(row.get(f"{category}目录"), f"{label}.{category}目录")
        for file_id in catalogs:
            members = data.pool_members((file_id,), category)
            if not members:
                raise JsonDataError(f"{label}引用空目录：{file_id}")
        result[category] = catalogs
    return result


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError(f"{label}必须是字符串数组")
    result = tuple(str(item).strip() for item in value)
    if not result or any(not item for item in result) or len(result) != len(set(result)):
        raise JsonDataError(f"{label}不能为空、重复或包含空值")
    return result


def _text(value: object, label: str) -> str:
    return nonempty_text(value, label, error=TradeError)


__all__ = ["TradeService"]
