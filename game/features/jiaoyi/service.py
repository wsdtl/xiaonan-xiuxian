"""地点交易查询与购买编排。"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from typing import TypeVar


from game.core.data import JsonDataError, JsonDataService
from game.core.trade import (
    TradeError,
    TradeOverview,
    TradePage,
    TradePurchaseCommand,
    TradePurchaseResult,
    TradeService,
)

from .contracts import TradeFeatureError


_Result = TypeVar("_Result")


class TradeFeature:
    """只编排交易核心和JSON展示，不持有玩家状态。"""

    def __init__(self, data: JsonDataService, trade: TradeService) -> None:
        self._data = data
        self._trade = trade
        self._copy: Mapping[str, object] | None = None

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("交易玩法已经初始化")
        if not self._trade.status().initialized:
            raise RuntimeError("交易核心必须先于交易玩法启动")
        copy = self._data.dataset("交易展示").get("文本")
        if not isinstance(copy, Mapping):
            raise JsonDataError("交易展示缺少文本.json")
        for section in ("总览", "列表", "购买", "错误"):
            if not isinstance(copy.get(section), Mapping):
                raise JsonDataError(f"交易展示缺少文本.{section}")
        self._copy = copy

    def copy(self, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
        if self._copy is None:
            raise RuntimeError("交易玩法尚未初始化")
        group = self._copy.get(section)
        value = group.get(key) if isinstance(group, Mapping) else None
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"交易展示缺少文本：{section}.{key}")
        return value.format_map(values or {})

    async def overview(self, user_id: str) -> TradeOverview:
        return await self._call(self._trade.overview(user_id))

    async def page(self, user_id: str, category: str, page: int) -> TradePage:
        return await self._call(self._trade.page(user_id, category, page))

    async def purchase(
        self, command: TradePurchaseCommand
    ) -> TradePurchaseResult:
        return await self._call(self._trade.purchase(command))

    @staticmethod
    async def _call(awaitable: Awaitable[_Result]) -> _Result:
        try:
            return await awaitable
        except TradeError as exc:
            raise TradeFeatureError(str(exc)) from exc


__all__ = ["TradeFeature"]
