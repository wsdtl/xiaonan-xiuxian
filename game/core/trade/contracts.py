"""地点交易核心微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass


class TradeError(RuntimeError):
    """地点交易无法完成请求。"""


class TradeConflictError(TradeError):
    """购买涉及的玩家状态已经变化。"""


@dataclass(frozen=True)
class TradeStatus:
    initialized: bool
    shop_count: int
    maximum_quantity: int


@dataclass(frozen=True)
class TradeCategorySummary:
    category: str
    product_count: int


@dataclass(frozen=True)
class TradeOverview:
    location_name: str
    spirit_stones: int
    categories: tuple[TradeCategorySummary, ...]


@dataclass(frozen=True)
class TradeProduct:
    category: str
    content_id: str
    name: str
    grade_id: str
    grade_name: str
    unit_price: int
    delivery: str


@dataclass(frozen=True)
class TradePage:
    location_name: str
    category: str
    page: int
    total_pages: int
    total_products: int
    products: tuple[TradeProduct, ...]


@dataclass(frozen=True)
class TradePurchaseCommand:
    user_id: str
    request_id: str
    identifier: str
    grade_id: str
    quantity: int = 1


@dataclass(frozen=True)
class TradePurchaseResult:
    location_name: str
    product: TradeProduct
    quantity: int
    total_price: int
    spirit_stones_after: int
    delivery_after: int
    replayed: bool


__all__ = [
    "TradeCategorySummary",
    "TradeConflictError",
    "TradeError",
    "TradeOverview",
    "TradePage",
    "TradeProduct",
    "TradePurchaseCommand",
    "TradePurchaseResult",
    "TradeStatus",
]
