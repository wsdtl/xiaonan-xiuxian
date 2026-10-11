"""万珍殿查询、存入与宗主发放编排。"""

from __future__ import annotations

from collections.abc import Mapping
from math import ceil
from types import MappingProxyType

from game.core.character import CharacterService
from game.core.data import (
    JsonDataError,
    JsonDataService,
    nonempty_text as _text,
    positive_int as _positive_int,
)
from game.core.item_catalog import ItemCatalogService
from game.core.location import LocationService
from game.core.player_state import PlayerStateService
from game.core.sect import SectService
from game.core.sect_assets import SectAssetEntry, SectAssetError, SectAssetService
def _has_cjk(value: str) -> bool:
    return any('\u4e00' <= ch <= '\u9fff' for ch in value)


from game.features.presentation import (
    DUNGEON_BUTTON_KEYS,
    project_unique_buttons,
    require_mapping,
)

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
        innate_treasure: InnateTreasureService,
    ) -> None:
        self._data = data
        self._assets = assets
        self._items = items
        self._character = character
        self._sect = sect
        self._location = location
        self._player_state = player_state
        self._innate_treasure = innate_treasure
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
        # 存入只收五类成品，声明写在数据里（`成品类别` 与 `存入.允许类别` 必须一致）。
        if list(storing.get("允许类别") or ()) != list(rule.get("成品类别") or ()):
            raise JsonDataError("万珍殿存入允许类别必须与成品类别一致")
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
        window = entries[offset : offset + self._page_limit]
        return WanzhenPage(
            normalized,
            current,
            page_count,
            len(entries),
            window,
            self._treasure_names(window),
        )

    def _treasure_names(self, entries: Sequence[SectAssetEntry]) -> dict[str, str]:
        """条目上的先天灵宝编号换成名字（给渲染层查表用；查不到就退回编号）。"""

        names: dict[str, str] = {}
        for entry in entries:
            identifier = str(getattr(entry, "treasure_id", "") or "").strip()
            if not identifier or identifier in names:
                continue
            try:
                names[identifier] = self._innate_treasure.resolve(identifier).name
            except Exception:  # noqa: BLE001 - 名字只是展示，查不到就用编号
                names[identifier] = identifier
        return names

    def match_entry(
        self, entries: Sequence[SectAssetEntry], query: str
    ) -> SectAssetEntry | None:
        """把玩家写法在一批条目里换成唯一那一条；找不到或多条说不清返回 None。

        写法按《阵法说明》第五节的「字符类别即界限」：
        含 `:` 是整条**条目键**（原汁原味）；只有数字是**内容编号**；
        含中文是**名字写法**——`名称`、`品级前缀 名称`、`名称[灵宝名]`，`数字[名字]` 这种混写不认。
        万珍殿发放、宗门战锁阵都用这一份，别各写一套。
        """
        text = str(query or '').strip()
        if not text:
            return None
        if ':' in text:
            for entry in entries:
                if entry.entry_key == text:
                    return entry
            return None
        mode = 'id' if text.isdecimal() else ('name' if _has_cjk(text) else 'raw')
        if mode == 'raw':
            return None
        grade_hint = ''
        parts = text.split(None, 1)
        if len(parts) == 2 and not _has_cjk(parts[0]) and parts[0].endswith(('品', '阶')):
            grade_hint, text = parts[0], parts[1].strip()
        bare = ''
        if text.endswith(']') and '[' in text:
            head, _, bare = text[:-1].partition('[')
            head, bare = head.strip(), bare.strip()
            if head.isdecimal():
                return None
            text = head
        names = self._treasure_names(entries)
        matched = [
            entry
            for entry in entries
            if self._entry_hits(entry, text, mode, grade_hint, bare, names)
        ]
        if len(matched) == 1:
            return matched[0]
        if len(matched) > 1:
            raise WanzhenFeatureError(
                self.copy(
                    "条目说不清",
                    {
                        "count": len(matched),
                        "name": text,
                        "entries": "、".join(
                            entry.grade_name + " " + entry.entry_key
                            for entry in matched[:4]
                        ),
                    },
                )
            )
        return None

    @staticmethod
    def _entry_hits(entry: SectAssetEntry, text: str, mode: str, grade_hint: str, bare: str, names: dict[str, str]) -> bool:
        """一条条目是否命中玩家写法。"""

        if mode == 'id':
            if str(getattr(entry, 'content_id', '')) != text:
                return False
        elif str(getattr(entry, 'name', '')) != text:
            return False
        if grade_hint and grade_hint not in str(getattr(entry, 'grade_name', '')):
            return False
        if bare:
            identifier = str(getattr(entry, 'treasure_id', '') or '')
            if not identifier or names.get(identifier, identifier) != bare:
                return False
        return True

    async def resolve_vault_entry(self, user_id: str, query: str) -> str:
        """万珍殿里把玩家写法换成条目键；认不出就**原样返回**，由核心按自己的话回绝。

        发放与宗门战锁阵共用这一份——它们看的都是本宗万珍殿。
        """
        vault = await self._assets.wanzhen(user_id)
        entry = self.match_entry(vault.entries, query)
        return entry.entry_key if entry is not None else str(query or '').strip()

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
            # 丹药不在基础物品目录里（那份只收灵植/灵矿/兽宝），它有自己的实体表。
            entities = self._data.entities("丹药")
            if query in entities:
                return query
            matches = tuple(
                content_id
                for content_id, value in entities.items()
                if str(value.get("名称") or "").strip() == query
            )
            if len(matches) != 1:
                template = str(self.copy().text.get("丹药找不到") or "").strip()
                if not template:
                    raise WanzhenFeatureError(f"纳戒里没有「{query}」这味丹药")
                raise WanzhenFeatureError(template.format(name=query))
            return matches[0]
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
    return project_unique_buttons(value, label=label, keys=DUNGEON_BUTTON_KEYS)
    return result


__all__ = ["WanzhenFeature"]
