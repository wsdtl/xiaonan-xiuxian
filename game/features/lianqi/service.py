"""炼器查询、审材与开炉的玩法编排。"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from typing import TypeVar


from game.core.data import JsonDataService
from game.core.forging import (
    ForgingError,
    ForgingLawList,
    ForgingOverview,
    ForgingPreview,
    ForgingResult,
    ForgingService,
)

from .contracts import (
    ForgingAction,
    ForgingCopy,
    ForgingEntry,
    ForgingFeatureError,
)
from .presentation import actions, load_presentation


_Result = TypeVar("_Result")


class ForgingFeature:
    """只编排炼器核心与 JSON 展示，不拥有玩家状态。"""

    def __init__(self, data: JsonDataService, forging: ForgingService) -> None:
        self._data = data
        self._forging = forging
        self._copy: ForgingCopy | None = None
        self._buttons: tuple[Mapping[str, str], ...] = ()

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("炼器玩法已经初始化")
        if not self._forging.status().initialized:
            raise RuntimeError("炼器核心必须先于炼器玩法启动")
        self._copy, self._buttons = load_presentation(self._data)

    def copy(self) -> ForgingCopy:
        if self._copy is None:
            raise RuntimeError("炼器玩法尚未初始化")
        return self._copy

    async def enter_direct(
        self, user_id: str, request_id: str, raw_message: str
    ) -> ForgingEntry:
        """解析直接炼器；分支与参数合规只由本玩法判定。"""

        query = str(raw_message or "").strip()
        if not query:
            return ForgingEntry("overview", overview=await self.overview(user_id))
        identifier, quantity = self._direct(query)
        preview = await self.preview(user_id, identifier, quantity)
        if not preview.can_forge:
            return ForgingEntry("preview", preview=preview)
        return ForgingEntry(
            "completed",
            result=await self.forge(
                user_id, request_id, identifier, quantity
            ),
        )

    async def enter_catalog(
        self, user_id: str, raw_message: str
    ) -> ForgingEntry:
        """解析炼器目录；阶段/页码与单条预览由本玩法判定。"""

        query = str(raw_message or "").strip()
        if not query:
            return ForgingEntry("overview", overview=await self.overview(user_id))
        if query in {"灵器", "法器", "法宝", "后天灵宝"}:
            return ForgingEntry(
                "law_list", laws=await self.laws(user_id, query)
            )
        return ForgingEntry(
            "preview", preview=await self.preview(user_id, query)
        )

    def _direct(self, query: str) -> tuple[str, int]:
        parts = str(query or "").strip().split()
        quantity = 1
        if len(parts) > 1 and parts[-1].isdecimal():
            quantity = int(parts[-1])
            parts = parts[:-1]
        if not parts:
            raise ValueError("缺少器律名")
        return " ".join(parts), quantity

    async def overview(self, user_id: str) -> ForgingOverview:
        return await self._call(self._forging.overview(user_id))

    async def laws(self, user_id: str, stage: str) -> ForgingLawList:
        return await self._call(self._forging.list_laws(user_id, stage))

    async def preview(self, user_id: str, identifier: str, quantity: int = 1) -> ForgingPreview:
        return await self._call(self._forging.preview(user_id, identifier, quantity))

    async def forge(
        self, user_id: str, request_id: str, identifier: str, quantity: int = 1
    ) -> ForgingResult:
        return await self._call(
            self._forging.forge(user_id, request_id, identifier, quantity)
        )


    def format_actions(self) -> tuple[object, ...]:
        """格式错误页的动作：只有「查看帮助」——完整用法在帮助组件里，不在错误里铺。"""

        return actions(self._buttons, "格式", set())
    def overview_actions(self) -> tuple[ForgingAction, ...]:
        return actions(self._buttons, "总览", set())

    def preview_actions(self, preview: ForgingPreview) -> tuple[ForgingAction, ...]:
        return actions(
            self._buttons,
            "预览",
            {"可以炼器"} if preview.can_forge else set(),
            {"器律": preview.law.name},
        )

    def completed_actions(self) -> tuple[ForgingAction, ...]:
        return actions(self._buttons, "完成", set())

    @staticmethod
    async def _call(awaitable: Awaitable[_Result]) -> _Result:
        try:
            return await awaitable
        except ForgingError as exc:
            raise ForgingFeatureError(str(exc)) from exc


__all__ = ["ForgingFeature"]
