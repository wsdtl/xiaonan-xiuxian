from __future__ import annotations

from collections.abc import Mapping

from game.core.data import JsonDataError, JsonDataService
from game.core.gift import GiftResult, GiftSendCommand, GiftService
from game.core.item_catalog import ItemCatalogService


class GiftFeature:
    def __init__(self, data: JsonDataService, gift: GiftService, item_catalog: ItemCatalogService) -> None:
        self._data = data
        self._gift = gift
        self._items = item_catalog
        self._copy: Mapping[str, object] | None = None

    def initialize(self) -> None:
        copy = self._data.dataset("赠送展示").get("文本")
        if not isinstance(copy, Mapping):
            raise JsonDataError("展示/赠送/文本.json 必须是对象")
        self._copy = copy

    def text(self, section: str, key: str, **values: object) -> str:
        if self._copy is None:
            raise RuntimeError("赠送玩法尚未初始化")
        group = self._copy.get(section) if section else self._copy
        result = group.get(key) if isinstance(group, Mapping) else None
        if not isinstance(result, str):
            raise TypeError(f"赠送展示缺少文本：{key}")
        return result.format_map(values)

    async def resolve_target(self, user_id: str, query: str) -> str:
        return await self._gift.resolve_target(user_id, query)

    async def send(self, command: GiftSendCommand) -> GiftResult:
        return await self._gift.send(command)

    def item_name(self, item_id: str) -> str:
        return self._items.get(item_id).name
