"""藏经阁查询和借阅编排。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import ceil
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService
from game.core.location import LocationService
from game.core.player_state import PlayerStateService
from game.core.sect import SectService
from game.core.sect_library import SectLibraryError, SectLibraryService
from game.features.presentation import require_mapping

from .contracts import CangjingAction, CangjingCopy, CangjingFeatureError, CangjingPage


class CangjingFeature:
    """只编排藏经阁核心，不拥有功法或宗门关系。"""

    def __init__(
        self,
        data: JsonDataService,
        library: SectLibraryService,
        sect: SectService,
        location: LocationService,
        player_state: PlayerStateService,
    ) -> None:
        self._data = data
        self._library = library
        self._sect = sect
        self._location = location
        self._player_state = player_state
        self._copy: CangjingCopy | None = None
        self._buttons: tuple[Mapping[str, str], ...] = ()
        self._page_limit = 0
        self._guard_rule = ""

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("藏经阁玩法已经初始化")
        if not self._library.status().initialized:
            raise RuntimeError("藏经阁核心必须先于藏经阁玩法启动")
        rule = require_mapping(self._data.dataset("宗门规则").get("藏经阁"), "藏经阁规则")
        borrowing = require_mapping(rule.get("借阅"), "藏经阁.借阅")
        self._page_limit = _positive_int(rule.get("每页上限"), "藏经阁.每页上限")
        self._guard_rule = _text(borrowing.get("状态守卫"), "藏经阁.借阅.状态守卫")
        raw_copy = require_mapping(self._data.dataset("藏经阁展示").get("文本"), "藏经阁展示")
        self._copy = CangjingCopy(
            MappingProxyType({str(key): str(value) for key, value in raw_copy.items()})
        )
        self._buttons = _buttons(
            self._data.dataset("藏经阁按钮").get("按钮"), "藏经阁按钮"
        )

    def copy(self) -> CangjingCopy:
        if self._copy is None:
            raise RuntimeError("藏经阁玩法尚未初始化")
        return self._copy

    def page_actions(self, value: CangjingPage) -> tuple[CangjingAction, ...]:
        variables = {"上一页": str(value.page - 1), "下一页": str(value.page + 1)}
        conditions = {""}
        if value.page > 1:
            conditions.add("有上一页")
        if value.page < value.page_count:
            conditions.add("有下一页")
        return tuple(
            CangjingAction(
                button["编号"],
                button["名称"],
                button["命令"].format_map(variables),
                button["行为"],
                button["样式"],
            )
            for button in self._buttons
            if button["条件"] in conditions
        )

    async def page(self, user_id: str, page: int = 1) -> CangjingPage:
        await self._require_cave(user_id)
        page_number = _positive_int(page, "藏经阁页码", CangjingFeatureError)
        try:
            view = await self._library.view(user_id)
        except SectLibraryError as exc:
            raise CangjingFeatureError(str(exc)) from exc
        page_count = max(1, ceil(len(view.techniques) / self._page_limit))
        current = min(page_number, page_count)
        offset = (current - 1) * self._page_limit
        return CangjingPage(
            current,
            page_count,
            len(view.techniques),
            view.techniques[offset : offset + self._page_limit],
        )

    async def borrow(self, user_id: str, request_id: str, identifier: str, slot: int):
        await self._require_cave(user_id)
        result = await self._player_state.authorize(user_id, self._guard_rule)
        if not result.allowed:
            raise CangjingFeatureError(result.reason)
        try:
            return await self._library.borrow(user_id, request_id, identifier, slot)
        except SectLibraryError as exc:
            raise CangjingFeatureError(str(exc)) from exc

    async def _require_cave(self, user_id: str) -> None:
        member = await self._sect.membership(user_id)
        if member is None:
            raise CangjingFeatureError("尚未加入宗门")
        sect = await self._sect.sect(member.sect_id)
        current = await self._location.current(user_id)
        if (
            sect is None
            or current.space_type != "宗门洞天"
            or current.space_id != sect.cave_id
        ):
            raise CangjingFeatureError("只有身处本宗洞天时才能使用藏经阁")


def _text(value: object, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise JsonDataError(f"{label}必须是非空字符串")
    return result


def _positive_int(value: object, label: str, error=JsonDataError) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise error(f"{label}必须是正整数")
    return value


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


__all__ = ["CangjingFeature"]
