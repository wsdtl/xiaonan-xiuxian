"""炼丹查询、验药和开炉的玩法编排。"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from typing import TypeVar

from game.core.alchemy import (
    AlchemyOverview,
    AlchemyRecipeList,
    AlchemyPreview,
    AlchemyResult,
    AlchemyError,
    AlchemyService,
)


from game.core.data import JsonDataService

from .contracts import AlchemyAction, AlchemyCopy, AlchemyFeatureError
from .presentation import actions, load_presentation


_Result = TypeVar("_Result")


class AlchemyFeature:
    """只编排炼丹核心与 JSON 展示，不拥有玩家状态。"""

    def __init__(self, data: JsonDataService, alchemy: AlchemyService) -> None:
        self._data = data
        self._alchemy = alchemy
        self._copy: AlchemyCopy | None = None
        self._buttons: tuple[Mapping[str, str], ...] = ()

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("炼丹玩法已经初始化")
        if not self._alchemy.status().initialized:
            raise RuntimeError("炼丹核心必须先于炼丹玩法启动")
        self._copy, self._buttons = load_presentation(self._data)

    def copy(self) -> AlchemyCopy:
        if self._copy is None:
            raise RuntimeError("炼丹玩法尚未初始化")
        return self._copy

    async def overview(self, user_id: str) -> AlchemyOverview:
        return await self._call(self._alchemy.overview(user_id))

    async def recipes(self, user_id: str, category: str, page: int = 1) -> AlchemyRecipeList:
        return await self._call(self._alchemy.list_recipes(user_id, category, page))

    async def preview(self, user_id: str, identifier: str) -> AlchemyPreview:
        return await self._call(self._alchemy.preview(user_id, identifier))

    async def refine(self, user_id: str, request_id: str, identifier: str) -> AlchemyResult:
        return await self._call(self._alchemy.refine(user_id, request_id, identifier))

    def overview_actions(self) -> tuple[AlchemyAction, ...]:
        return actions(self._buttons, "总览", set())

    def list_actions(self, value: AlchemyRecipeList) -> tuple[AlchemyAction, ...]:
        conditions = set()
        if value.page > 1:
            conditions.add("有上一页")
        if value.page < value.page_count:
            conditions.add("有下一页")
        result: list[AlchemyAction] = []
        for condition, page in (("有上一页", value.page - 1), ("有下一页", value.page + 1)):
            if condition in conditions:
                result.extend(
                    actions(
                        self._buttons,
                        "列表",
                        {condition},
                        {"分类": value.category, "页码": page},
                    )
                )
        return tuple(result)

    def preview_actions(self, value: AlchemyPreview) -> tuple[AlchemyAction, ...]:
        return actions(
            self._buttons,
            "预览",
            {"可以开炉"} if value.can_refine else set(),
            {"丹药": value.recipe.recipe_id},
        )

    def completed_actions(self) -> tuple[AlchemyAction, ...]:
        return actions(self._buttons, "完成", set())

    @staticmethod
    async def _call(awaitable: Awaitable[_Result]) -> _Result:
        try:
            return await awaitable
        except AlchemyError as exc:
            raise AlchemyFeatureError(str(exc)) from exc


__all__ = ["AlchemyFeature"]
