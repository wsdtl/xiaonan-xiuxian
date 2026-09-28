"""宗门设施入口编排；炼器、炼丹和炼阵公式仍归各自核心。"""

from __future__ import annotations

from game.core.sect_facilities import (
    SectForgingPreview,
    SectAlchemyPreview,
    SectFormationPreview,
    SectCraftResult,
    SectFacilityPage,
    SectFacilityError,
    SectFacilityService,
)

from collections.abc import Mapping

from game.core.data import JsonDataError, JsonDataService


class SectFacilityFeatureError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SectFacilityFeature:
    def __init__(self, data: JsonDataService, facilities: SectFacilityService) -> None:
        self._data = data
        self._facilities = facilities
        self._copy: Mapping[str, Mapping[str, str]] | None = None

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("宗门设施玩法已经初始化")
        raw = self._data.dataset("宗门设施展示").get("文本")
        if not isinstance(raw, Mapping):
            raise JsonDataError("宗门设施展示缺少文本.json")
        self._copy = raw

    def copy(self) -> Mapping[str, Mapping[str, str]]:
        if self._copy is None:
            raise RuntimeError("宗门设施玩法尚未初始化")
        return self._copy

    async def page(
        self,
        facility: str,
        user_id: str,
        source: str = "个人纳戒",
        section: str = "",
        page: int = 1,
    ) -> SectFacilityPage:
        source = _source(source)
        try:
            if facility == "炼器":
                return await self._facilities.forging_page(user_id, source, section, page)
            if facility == "炼丹":
                return await self._facilities.alchemy_page(user_id, source, section, page)
            if facility == "炼阵":
                return await self._facilities.formation_page(user_id, source, page)
        except (SectFacilityError, ValueError) as exc:
            raise SectFacilityFeatureError(str(exc)) from exc
        raise SectFacilityFeatureError("未知宗门设施")

    async def preview(self, facility: str, user_id: str, source: str, identifier: str, grade: str = "", investments: Mapping[str, int] | None=None) -> SectForgingPreview | SectAlchemyPreview | SectFormationPreview:
        source = _source(source)
        try:
            if facility == "炼器":
                return await self._facilities.preview_forging(user_id, identifier, source)
            if facility == "炼丹":
                return await self._facilities.preview_alchemy(user_id, identifier, source)
            if facility == "炼阵":
                if not grade:
                    raise SectFacilityError("炼阵必须指定品级")
                return await self._facilities.preview_formation(
                    user_id, identifier, grade, source, investments
                )
        except (SectFacilityError, ValueError) as exc:
            raise SectFacilityFeatureError(str(exc)) from exc
        raise SectFacilityFeatureError("未知宗门设施")

    async def craft(self, facility: str, user_id: str, request_id: str, source: str, identifier: str, grade: str = "", investments: Mapping[str, int] | None=None) -> SectCraftResult:
        source = _source(source)
        try:
            if facility == "炼器":
                return await self._facilities.forge(user_id, request_id, identifier, source)
            if facility == "炼丹":
                return await self._facilities.refine(user_id, request_id, identifier, source)
            if facility == "炼阵":
                return await self._facilities.form(
                    user_id, request_id, identifier, grade, source, investments
                )
        except (SectFacilityError, ValueError) as exc:
            raise SectFacilityFeatureError(str(exc)) from exc
        raise SectFacilityFeatureError("未知宗门设施")


def _source(value: str) -> str:
    normalized = str(value or "个人").strip()
    if normalized in {"个人", "自备", "纳戒", "个人纳戒"}:
        return "个人纳戒"
    if normalized in {"宗门", "灵藏", "宗门灵藏"}:
        return "宗门灵藏"
    raise SectFacilityFeatureError("材料来源只能是个人或宗门")


__all__ = ["SectFacilityFeature", "SectFacilityFeatureError"]
