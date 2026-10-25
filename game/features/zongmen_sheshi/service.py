"""宗门设施入口编排；炼器、炼丹和炼阵公式仍归各自核心。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _SheshiAction:
    """宗门设施回执上的动作，字段名与 CommandAction 契约一致。"""

    action_id: str
    label: str
    command: str
    behavior: str
    style: str

from game.core.formation import FormationChoiceError

from game.core.sect_facilities import (
    SectForgingPreview,
    SectAlchemyPreview,
    SectFormationPreview,
    SectCraftResult,
    SectFacilityPage,
    SectFacilityError,
    SectFacilityService,
)

from collections.abc import Mapping, Sequence

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
        common = self._data.dataset("炼制通用文案").get("炼制通用")
        if not isinstance(common, Mapping):
            raise JsonDataError("宗门设施展示缺少通用.json")
        raw = {
            "通用": common.get("通用"),
            "错误": common.get("错误"),
        }
        texts = {
            "百炼堂": self._data.dataset("百炼堂页面文案").get("文本"),
            "丹鼎阁": self._data.dataset("丹鼎阁页面文案").get("文本"),
            "演阵台": self._data.dataset("演阵台页面文案").get("文本"),
        }
        button_rows = {
            "百炼堂": self._data.dataset("百炼堂页面按钮").get("按钮") or (),
            "丹鼎阁": self._data.dataset("丹鼎阁页面按钮").get("按钮") or (),
            "演阵台": self._data.dataset("演阵台页面按钮").get("按钮") or (),
        }
        buttons: list[Mapping[str, object]] = []
        for name in ("百炼堂", "丹鼎阁", "演阵台"):
            section = texts[name]
            if not isinstance(section, Mapping):
                raise JsonDataError(f"{name}展示缺少文本.json")
            raw[name] = section
            rows = button_rows[name]
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                raise JsonDataError(f"{name}按钮必须是字典列表")
            buttons.extend(row for row in rows if isinstance(row, Mapping))
        self._format_buttons = tuple(
            (str(row["页面"]), str(row["编号"]), str(row["名称"]), str(row["命令"]), str(row["行为"]), str(row["样式"]))
            for row in buttons
        )
        self._copy = raw

    def grades(self, facility: str = "炼阵") -> tuple[str, ...]:
        """这一设施支持哪些品级（黄品/玄品/…）：核心自己声明的，页面照印不自己造。

        演阵台的品级下拉原先发号段编号 `01`–`05`，而阵法核心只认品级名——选哪个都被拒。
        触发层不许碰核心，所以由这里把核心的公开结果转出来。
        """

        return tuple(self._facilities.facility(facility).supported_grades)

    def formation_catalog(self) -> tuple[tuple[str, str], ...]:
        """全部阵法（编号, 名称）——页面在核心列不出个人阵法时退回的那份总目。"""

        return tuple(
            sorted(
                (str(key), str(value.get("名称") or ""))
                for key, value in self._data.entities("阵法").items()
            )
        )

    def format_actions(self, page: str) -> tuple[object, ...]:
        """格式与提示类回执的动作：只给该设施页面的「查看帮助」。"""

        return tuple(
            _SheshiAction(entry_id, entry_name, command, behavior, style)
            for (page_id, entry_id, entry_name, command, behavior, style) in self._format_buttons
            if page_id == page
        )


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
        except FormationChoiceError:
            # 「阵藏里有多条」不是错误，是要玩家挑一件：原样放行给命令层铺选择卡。
            raise
        except (SectFacilityError, ValueError) as exc:
            raise SectFacilityFeatureError(str(exc)) from exc
        raise SectFacilityFeatureError("未知宗门设施")

    async def preview(self, facility: str, user_id: str, source: str, identifier: str, grade: str = "", investments: Mapping[str, int] | None=None) -> SectForgingPreview | SectAlchemyPreview | SectFormationPreview:
        source = _source(source)
        try:
            if facility == "炼器":
                return await self._facilities.preview_forging(user_id, identifier, source)
            if facility == "炼丹":
                return await self._facilities.preview_alchemy(
                    user_id, identifier, source, grade or "黄品"
                )
            if facility == "炼阵":
                if not grade:
                    raise SectFacilityError("炼阵必须指定品级")
                return await self._facilities.preview_formation(
                    user_id, identifier, grade, source, investments
                )
        except FormationChoiceError:
            # 「阵藏里有多条」不是错误，是要玩家挑一件：原样放行给命令层铺选择卡。
            raise
        except (SectFacilityError, ValueError) as exc:
            raise SectFacilityFeatureError(str(exc)) from exc
        raise SectFacilityFeatureError("未知宗门设施")

    async def craft(self, facility: str, user_id: str, request_id: str, source: str, identifier: str, grade: str = "", investments: Mapping[str, int] | None=None) -> SectCraftResult:
        source = _source(source)
        try:
            if facility == "炼器":
                return await self._facilities.forge(user_id, request_id, identifier, source)
            if facility == "炼丹":
                return await self._facilities.refine(
                    user_id, request_id, identifier, source, grade or "黄品"
                )
            if facility == "炼阵":
                return await self._facilities.form(
                    user_id, request_id, identifier, grade, source, investments
                )
        except FormationChoiceError:
            # 「阵藏里有多条」不是错误，是要玩家挑一件：原样放行给命令层铺选择卡。
            raise
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
