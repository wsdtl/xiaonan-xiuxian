"""灵藏查询与捐献编排。"""

from __future__ import annotations

from game.core.sect_assets import SectAssetTransfer, SectAssetError, SectAssetService

from collections.abc import Mapping, Sequence
from math import ceil
from types import MappingProxyType

from game.core.data import (
    JsonDataError,
    JsonDataService,
    nonempty_text as _text,
    positive_int as _positive_int,
)
from game.core.item_catalog import ItemCatalogError, ItemCatalogService
from game.core.location import LocationService
from game.core.player_state import PlayerStateService
from game.core.sect import SectService
from game.features.presentation import require_mapping

from .contracts import LingcangAction, LingcangCopy, LingcangFeatureError, LingcangPage


class LingcangFeature:
    """只编排灵藏核心，不拥有宗门或个人资产。"""

    def __init__(
        self,
        data: JsonDataService,
        assets: SectAssetService,
        items: ItemCatalogService,
        sect: SectService,
        location: LocationService,
        player_state: PlayerStateService,
    ) -> None:
        self._data = data
        self._assets = assets
        self._items = items
        self._sect = sect
        self._location = location
        self._player_state = player_state
        self._copy: LingcangCopy | None = None
        self._buttons: tuple[Mapping[str, str], ...] = ()
        self._page_limit = 0
        self._guard_rule = ""

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("灵藏玩法已经初始化")
        if not self._assets.status().initialized:
            raise RuntimeError("宗门公共资产核心必须先于灵藏玩法启动")
        rule = require_mapping(self._data.dataset("宗门规则").get("灵藏"), "灵藏规则")
        storing = require_mapping(rule.get("存入"), "灵藏.存入")
        self._page_limit = _positive_int(rule.get("每页上限"), "灵藏.每页上限")
        self._guard_rule = _text(storing.get("状态守卫"), "灵藏.存入.状态守卫")
        raw_copy = require_mapping(self._data.dataset("灵藏展示").get("文本"), "灵藏展示")
        self._copy = LingcangCopy(
            MappingProxyType({str(key): str(value) for key, value in raw_copy.items()})
        )
        self._buttons = _buttons(self._data.dataset("灵藏按钮").get("按钮"), "灵藏按钮")

    def copy(self) -> LingcangCopy:
        if self._copy is None:
            raise RuntimeError("灵藏玩法尚未初始化")
        return self._copy

    def page_actions(self, value: LingcangPage) -> tuple[LingcangAction, ...]:
        variables = {
            "分类": value.category,
            "上一页": str(value.page - 1),
            "下一页": str(value.page + 1),
        }
        conditions = {""}
        if value.page > 1:
            conditions.add("有上一页")
        if value.page < value.page_count:
            conditions.add("有下一页")
        return tuple(
            LingcangAction(
                button["编号"],
                button["名称"],
                button["命令"].format_map(variables),
                button["行为"],
                button["样式"],
            )
            for button in self._buttons
            if button["条件"] in conditions
        )

    async def page(
        self, user_id: str, category: str = "全部", page: int = 1
    ) -> LingcangPage:
        await self._require_cave(user_id)
        normalized = str(category or "全部").strip()
        allowed = ("全部", *self._assets.status().material_categories)
        if normalized not in allowed:
            raise LingcangFeatureError(f"灵藏不支持分类：{normalized or '<空>'}")
        page_number = _positive_int(page, "灵藏页码", LingcangFeatureError)
        try:
            vault = await self._assets.lingcang(user_id)
        except SectAssetError as exc:
            raise LingcangFeatureError(str(exc)) from exc
        entries = tuple(
            value
            for value in vault.entries
            if normalized == "全部" or value.category == normalized
        )
        page_count = max(1, ceil(len(entries) / self._page_limit))
        current = min(page_number, page_count)
        offset = (current - 1) * self._page_limit
        return LingcangPage(
            vault.spirit_stones,
            normalized,
            current,
            page_count,
            len(entries),
            entries[offset : offset + self._page_limit],
        )

    async def donate_material(
        self,
        user_id: str,
        request_id: str,
        category: str,
        identifier: str,
        grade: str,
        quantity: int,
    ) -> SectAssetTransfer:
        await self._require_write(user_id)
        try:
            item = self._items.inspect(identifier)
            if item.category != category:
                raise LingcangFeatureError(f"{item.name}不属于{category}")
            return await self._assets.donate_material(
                user_id, request_id, category, item.item_id, grade, quantity
            )
        except ItemCatalogError as exc:
            raise LingcangFeatureError(str(exc)) from exc
        except SectAssetError as exc:
            raise LingcangFeatureError(str(exc)) from exc

    async def donate_stones(self, user_id: str, request_id: str, quantity: int) -> SectAssetTransfer:
        await self._require_write(user_id)
        try:
            return await self._assets.donate_stones(user_id, request_id, quantity)
        except SectAssetError as exc:
            raise LingcangFeatureError(str(exc)) from exc

    async def _require_write(self, user_id: str) -> None:
        await self._require_cave(user_id)
        result = await self._player_state.authorize(user_id, self._guard_rule)
        if not result.allowed:
            raise LingcangFeatureError(result.reason)

    async def _require_cave(self, user_id: str) -> None:
        member = await self._sect.membership(user_id)
        if member is None:
            raise LingcangFeatureError("尚未加入宗门")
        sect = await self._sect.sect(member.sect_id)
        current = await self._location.current(user_id)
        if (
            sect is None
            or current.space_type != "宗门洞天"
            or current.space_id != sect.cave_id
        ):
            raise LingcangFeatureError("只有身处本宗洞天时才能使用灵藏（先入山门进洞天）")


def _buttons(value: object, label: str) -> tuple[Mapping[str, str], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError(f"{label}必须是字典列表")
    keys = ("条件", "编号", "名称", "命令", "行为", "样式")
    result = tuple(
        MappingProxyType(
            {
                key: str(require_mapping(raw, f"{label}[]").get(key) or "").strip()
                for key in keys
            }
        )
        for raw in value
    )
    if len({button["编号"] for button in result}) != len(result):
        raise JsonDataError(f"{label}按钮编号不能重复")
    if any(
        not button["编号"]
        or not button["命令"]
        or button["行为"] not in {"callback", "send", "fill", "link"}
        for button in result
    ):
        raise JsonDataError(f"{label}存在不完整按钮")
    return result


__all__ = ["LingcangFeature"]
