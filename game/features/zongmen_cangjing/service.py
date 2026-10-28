"""藏经阁查询和借阅编排。"""

from __future__ import annotations

from game.core.sect_library import SectBorrowResult, SectLibraryError, SectLibraryService

from collections.abc import Mapping
from math import ceil
from types import MappingProxyType

from game.core.character import CharacterService, CharacterStateError
from game.core.data import (
    JsonDataService,
    nonempty_text as _text,
    positive_int as _positive_int,
)
from game.core.location import LocationService
from game.core.player_state import PlayerStateService
from game.core.sect import SectService
from game.features.presentation import (
    project_dungeon_buttons,
    require_mapping,
)

from .contracts import (
    CangjingAction,
    CangjingCopy,
    CangjingEntry,
    CangjingFeatureError,
    CangjingPage,
)


class CangjingFeature:
    """只编排藏经阁核心，不拥有功法或宗门关系。"""

    def __init__(
        self,
        data: JsonDataService,
        library: SectLibraryService,
        sect: SectService,
        character: CharacterService,
        location: LocationService,
        player_state: PlayerStateService,
    ) -> None:
        self._data = data
        self._library = library
        self._sect = sect
        self._character = character
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
        rule = require_mapping(self._data.dataset("藏经阁借阅规则").get("藏经阁"), "藏经阁规则")
        borrowing = require_mapping(rule.get("借阅"), "藏经阁.借阅")
        self._page_limit = _positive_int(rule.get("每页上限"), "藏经阁.每页上限")
        self._guard_rule = _text(borrowing.get("状态守卫"), "藏经阁.借阅.状态守卫")
        raw_copy = require_mapping(self._data.dataset("藏经阁页面文案").get("文本"), "藏经阁展示")
        self._copy = CangjingCopy(
            MappingProxyType({str(key): str(value) for key, value in raw_copy.items()})
        )
        self._buttons = project_dungeon_buttons(
            self._data.dataset("藏经阁页面按钮").get("按钮"), "藏经阁按钮"
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

    async def enter(
        self, user_id: str, request_id: str, raw_message: str
    ) -> CangjingEntry:
        """解析藏经阁根命令；分支与参数合规只由本玩法判定。"""

        copy = self.copy()
        parts = str(raw_message or "").strip().split(maxsplit=1)
        if not parts:
            return CangjingEntry("page", page=await self.page(user_id, 1))
        action = parts[0]
        rest = parts[1].strip() if len(parts) > 1 else ""
        if action.isdecimal():
            return CangjingEntry(
                "page", page=await self.page(user_id, self._positive(action, "藏经阁页码"))
            )
        if action != "借阅":
            raise CangjingFeatureError(copy.text["分支"])
        words = rest.split()
        if not words:
            raise CangjingFeatureError(copy.text["借阅写法"])
        identifier = words[0]
        if len(words) == 1:
            slots = await self.borrow_slots(user_id)
            if slots < 1:
                raise CangjingFeatureError("没有可用的功法槽")
            return CangjingEntry("prompt", identifier=identifier, slots=slots)
        if len(words) != 2:
            raise CangjingFeatureError(copy.text["借阅写法"])
        slot = self._positive(words[1], "功法槽位")
        return CangjingEntry(
            "borrowed",
            borrowed=await self.borrow(user_id, request_id, identifier, slot),
        )

    def _positive(self, value: str, label: str) -> int:
        if not value.isdecimal() or int(value) < 1:
            raise CangjingFeatureError(f"{label}必须是正整数")
        return int(value)

    async def borrow_slots(self, user_id: str) -> int:
        """先确认在洞天且可行动，再返回可借入的功法槽数量。"""

        if self._copy is None:
            raise RuntimeError("藏经阁玩法尚未初始化")
        await self._require_cave(user_id)
        result = await self._player_state.authorize(user_id, self._guard_rule)
        if not result.allowed:
            raise CangjingFeatureError(result.reason)
        return int(self._character.assembly_limits().get("功法", 0))

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

    async def borrow(self, user_id: str, request_id: str, identifier: str, slot: int) -> SectBorrowResult:
        await self._require_cave(user_id)
        result = await self._player_state.authorize(user_id, self._guard_rule)
        if not result.allowed:
            raise CangjingFeatureError(result.reason)
        try:
            member, technique = await self._library.borrow_target(
                user_id, identifier, slot
            )
            plan = await self._character.plan_borrow_slot(
                user_id,
                slot,
                technique.content_id,
                technique.grade_id,
                member.sect_id,
            )
            return await self._library.commit_borrow(
                user_id,
                request_id,
                member,
                technique,
                slot,
                plan.operations,
            )
        except CharacterStateError as exc:
            raise CangjingFeatureError(str(exc)) from exc
        except SectLibraryError as exc:
            raise CangjingFeatureError(str(exc)) from exc

    async def _require_cave(self, user_id: str) -> None:
        member = await self._sect.membership(user_id)
        if member is None:
            raise CangjingFeatureError("尚未加入宗门")
        sect = await self._sect.sect(member.sect_id)
        current = await self._location.current(user_id)
        if sect is None or current.xy != sect.entrance_xy:
            raise CangjingFeatureError("只有在本宗园区才能使用藏经阁")


__all__ = ["CangjingFeature"]
