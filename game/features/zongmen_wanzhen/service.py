"""万珍殿查询、存入与宗主发放编排。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import ceil
from types import MappingProxyType

from game.core.character import CharacterService
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
from game.core.sect_assets import SectAssetError, SectAssetService
from game.features.presentation import require_mapping

from .contracts import (
    WanzhenAction,
    WanzhenCopy,
    WanzhenFeatureError,
    WanzhenPage,
    WanzhenTransferResult,
)


class WanzhenFeature:
    """只编排万珍殿核心，不拥有个人资产或成员关系。"""

    def __init__(
        self,
        data: JsonDataService,
        assets: SectAssetService,
        items: ItemCatalogService,
        character: CharacterService,
        sect: SectService,
        location: LocationService,
        player_state: PlayerStateService,
    ) -> None:
        self._data = data
        self._assets = assets
        self._items = items
        self._character = character
        self._sect = sect
        self._location = location
        self._player_state = player_state
        self._copy: WanzhenCopy | None = None
        self._buttons: tuple[Mapping[str, str], ...] = ()
        self._page_limit = 0
        self._guard_rule = ""

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("万珍殿玩法已经初始化")
        if not self._assets.status().initialized:
            raise RuntimeError("宗门公共资产核心必须先于万珍殿玩法启动")
        rule = require_mapping(self._data.dataset("宗门规则").get("万珍殿"), "万珍殿规则")
        storing = require_mapping(rule.get("存入"), "万珍殿.存入")
        distribution = require_mapping(rule.get("发放"), "万珍殿.发放")
        store_guard = _text(storing.get("状态守卫"), "万珍殿.存入.状态守卫")
        grant_guard = _text(distribution.get("状态守卫"), "万珍殿.发放.状态守卫")
        if store_guard != grant_guard:
            raise JsonDataError("万珍殿存入和发放必须使用同一状态守卫")
        self._guard_rule = store_guard
        self._page_limit = _positive_int(rule.get("每页上限"), "万珍殿.每页上限")
        raw_copy = require_mapping(self._data.dataset("万珍殿展示").get("文本"), "万珍殿展示")
        self._copy = WanzhenCopy(
            MappingProxyType({str(key): str(value) for key, value in raw_copy.items()})
        )
        self._buttons = _buttons(
            self._data.dataset("万珍殿按钮").get("按钮"), "万珍殿按钮"
        )

    def copy(self) -> WanzhenCopy:
        if self._copy is None:
            raise RuntimeError("万珍殿玩法尚未初始化")
        return self._copy

    def page_actions(self, value: WanzhenPage) -> tuple[WanzhenAction, ...]:
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
            WanzhenAction(
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
    ) -> WanzhenPage:
        await self._require_cave(user_id)
        normalized = str(category or "全部").strip()
        allowed = ("全部", *self._assets.status().product_categories)
        if normalized not in allowed:
            raise WanzhenFeatureError(f"万珍殿不支持分类：{normalized or '<空>'}")
        page_number = _positive_int(page, "万珍殿页码", WanzhenFeatureError)
        try:
            vault = await self._assets.wanzhen(user_id)
        except SectAssetError as exc:
            raise WanzhenFeatureError(str(exc)) from exc
        entries = tuple(
            value
            for value in vault.entries
            if normalized == "全部" or value.category == normalized
        )
        page_count = max(1, ceil(len(entries) / self._page_limit))
        current = min(page_number, page_count)
        offset = (current - 1) * self._page_limit
        return WanzhenPage(
            normalized,
            current,
            page_count,
            len(entries),
            entries[offset : offset + self._page_limit],
        )

    async def donate(
        self,
        user_id: str,
        request_id: str,
        category: str,
        identifier: str,
        grade_or_key: str,
        quantity: int,
    ) -> WanzhenTransferResult:
        await self._require_write(user_id)
        content_id = self._resolve_content(category, identifier)
        if category == "阵法":
            content_id, grade_or_key, quantity = "", identifier, 1
        try:
            result = await self._assets.donate_product(
                user_id,
                request_id,
                category,
                content_id,
                grade_or_key,
                quantity,
            )
        except SectAssetError as exc:
            raise WanzhenFeatureError(str(exc)) from exc
        if result.entry is None:
            raise WanzhenFeatureError("万珍殿存入结果缺少条目")
        return WanzhenTransferResult("存入", result.entry)

    async def grant(
        self,
        user_id: str,
        request_id: str,
        target: str,
        entry_key: str,
        quantity: int,
    ) -> WanzhenTransferResult:
        await self._require_write(user_id)
        target_id, target_name = await self._resolve_member(user_id, target)
        try:
            result = await self._assets.grant_product(
                user_id, request_id, target_id, entry_key, quantity
            )
        except SectAssetError as exc:
            raise WanzhenFeatureError(str(exc)) from exc
        if result.entry is None:
            raise WanzhenFeatureError("万珍殿发放结果缺少条目")
        return WanzhenTransferResult("发放", result.entry, target_name)

    def _resolve_content(self, category: str, identifier: str) -> str:
        normalized_category = str(category or "").strip()
        query = str(identifier or "").strip()
        if normalized_category == "丹药":
            try:
                return self._items.inspect(query).item_id
            except ItemCatalogError as exc:
                raise WanzhenFeatureError(str(exc)) from exc
        if normalized_category == "阵法":
            return ""
        if normalized_category not in {"真意", "气机", "器律"}:
            raise WanzhenFeatureError(
                f"万珍殿不支持分类：{normalized_category or '<空>'}"
            )
        entities = self._data.entities(normalized_category)
        if query in entities:
            return query
        matches = tuple(
            content_id
            for content_id, value in entities.items()
            if str(value.get("名称") or "").strip() == query
        )
        if len(matches) != 1:
            raise WanzhenFeatureError(
                f"没有找到唯一{normalized_category}：{query or '<空>'}"
            )
        return matches[0]

    async def _resolve_member(self, user_id: str, query: str) -> tuple[str, str]:
        member = await self._sect.membership(user_id)
        if member is None:
            raise WanzhenFeatureError("尚未加入宗门")
        members = await self._sect.members(member.sect_id)
        profiles = await self._character.public_profiles(
            tuple(value.user_id for value in members)
        )
        normalized = str(query or "").strip()
        direct = next(
            (value for value in profiles if value.user_id == normalized), None
        )
        if direct is not None:
            return direct.user_id, direct.name
        matches = tuple(value for value in profiles if value.name == normalized)
        if len(matches) != 1:
            raise WanzhenFeatureError("没有找到唯一的本宗成员")
        return matches[0].user_id, matches[0].name

    async def _require_write(self, user_id: str) -> None:
        await self._require_cave(user_id)
        result = await self._player_state.authorize(user_id, self._guard_rule)
        if not result.allowed:
            raise WanzhenFeatureError(result.reason)

    async def _require_cave(self, user_id: str) -> None:
        member = await self._sect.membership(user_id)
        if member is None:
            raise WanzhenFeatureError("尚未加入宗门")
        sect = await self._sect.sect(member.sect_id)
        current = await self._location.current(user_id)
        if (
            sect is None
            or current.space_type != "宗门洞天"
            or current.space_id != sect.cave_id
        ):
            raise WanzhenFeatureError("只有身处本宗洞天时才能使用万珍殿")


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


__all__ = ["WanzhenFeature"]
