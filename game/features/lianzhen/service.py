"""阵法浏览、审材与炼阵玩法编排。"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from typing import TypeVar

from game.core.formation import (
    FormationOverview,
    FormationPreview,
    FormationResult,
    FormationError,
    FormationService,
)
from .contracts import FormationCopy, FormationCraftFeatureError

from game.core.data import JsonDataService

from .presentation import actions, load_presentation, FormationAction


_Result = TypeVar("_Result")


class FormationCraftFeature:
    """只编排阵法核心与炼阵展示。"""

    def __init__(self, data: JsonDataService, formation: FormationService) -> None:
        self._data = data
        self._formation = formation
        self._copy = None
        self._buttons = ()

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("炼阵玩法已经初始化")
        if not self._formation.status().initialized:
            raise RuntimeError("阵法核心必须先于炼阵玩法启动")
        self._copy, self._buttons = load_presentation(self._data)

    def copy(self) -> FormationCopy:
        if self._copy is None:
            raise RuntimeError("炼阵玩法尚未初始化")
        return self._copy

    async def overview(self, user_id: str, page: int = 1) -> FormationOverview:
        return await self._call(self._formation.overview(user_id, page))

    async def preview(self, user_id: str, identifier: str, grade: str, investments: Mapping[str, int] | None=None) -> FormationPreview:
        return await self._call(self._formation.preview(user_id, identifier, grade, investments))

    async def form(self, user_id: str, request_id: str, identifier: str, grade: str, investments: Mapping[str, int] | None=None) -> FormationResult:
        return await self._call(self._formation.form(user_id, request_id, identifier, grade, investments))

    def overview_actions(self, value: FormationOverview) -> tuple[FormationAction, ...]:
        result = []
        if value.page > 1:
            result.extend(actions(self._buttons, "总览", {"有上一页"}, {"页码": value.page - 1}))
        if value.page < value.page_count:
            result.extend(actions(self._buttons, "总览", {"有下一页"}, {"页码": value.page + 1}))
        return tuple(result)

    def preview_actions(self, value: FormationPreview) -> tuple[FormationAction, ...]:
        return actions(
            self._buttons,
            "预览",
            {"可以炼阵"} if value.can_form else set(),
            {"请求": value.request_text},
        )

    def completed_actions(self) -> tuple[FormationAction, ...]:
        return actions(self._buttons, "完成", set())

    @staticmethod
    async def _call(awaitable: Awaitable[_Result]) -> _Result:
        try:
            return await awaitable
        except FormationError as exc:
            raise FormationCraftFeatureError(str(exc)) from exc


__all__ = ["FormationCraftFeature"]
