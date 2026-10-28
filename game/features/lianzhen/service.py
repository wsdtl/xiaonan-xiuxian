"""阵法浏览、审材与炼阵玩法编排。"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from typing import TypeVar

from game.core.formation import (
    FormationChoiceError,
    FormationOverview,
    FormationPreview,
    FormationResult,
    FormationError,
    FormationService,
)
from .contracts import FormationCopy, FormationCraftFeatureError, FormationEntry

from game.core.asset import AssetService
from game.core.data import JsonDataService
from game.features.presentation import parse_item_ref

from .presentation import actions, load_presentation, FormationAction


_Result = TypeVar("_Result")


class FormationCraftFeature:
    """只编排阵法核心与炼阵展示。"""

    def __init__(self, data: JsonDataService, formation: FormationService, asset: AssetService) -> None:
        self._data = data
        self._formation = formation
        self._asset = asset
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

    def grade_prefix(self, value: str) -> str:
        """受理品级的三种写法（黄品／黄／01），吐**全名**（黄品……）。

        规则：不许用短名（黄 要写 黄品）。资产核心的品级表本来就收全称、单字和编号；
        认不出的写法由核心按自己的话回绝（`InventoryChangeError`）。
        """

        resolved = self._asset.grade(value)
        name = str(getattr(resolved, "name", "") or "").strip()
        return name or str(value)

    async def enter(
        self, user_id: str, request_id: str, raw_message: str
    ) -> FormationEntry:
        """解析炼阵根命令；分支与参数合规只由本玩法判定。"""

        query = str(raw_message or "").strip()
        if not query:
            return FormationEntry(
                "overview", overview=await self.overview(user_id)
            )
        identifier, grade, investments, explicit = self._request(query)
        if not explicit:
            return FormationEntry("choose_grade", identifier=identifier)
        preview = await self.preview(
            user_id, identifier, grade, investments
        )
        if not preview.can_form:
            return FormationEntry("preview", preview=preview)
        return FormationEntry(
            "completed",
            result=await self.form(
                user_id, request_id, identifier, grade, investments
            ),
        )

    async def enter_catalog(
        self, user_id: str, raw_message: str
    ) -> FormationEntry:
        query = str(raw_message or "").strip()
        if not query:
            return FormationEntry(
                "overview", overview=await self.overview(user_id)
            )
        if query.isdecimal():
            page = int(query)
            if page < 1:
                raise ValueError("写法：炼阵目录 [页码]")
            return FormationEntry(
                "overview", overview=await self.overview(user_id, page)
            )
        identifier, grade, investments, explicit = self._request(query)
        if not explicit:
            return FormationEntry("choose_grade", identifier=identifier)
        return FormationEntry(
            "preview",
            preview=await self.preview(
                user_id, identifier, grade, investments
            ),
        )

    def _request(
        self, query: str
    ) -> tuple[str, str, dict[str, int] | None, bool]:
        parts = str(query or "").strip().split()
        if len(parts) == 1 and parts[0]:
            try:
                ref = parse_item_ref(parts[0])
            except Exception:
                ref = None
            if ref is not None and (ref.grade or ref.item):
                try:
                    grade = self.grade_prefix(ref.grade or "01")
                except Exception:
                    grade = ""
                if grade:
                    investments = None
                    if ref.extra:
                        investments = {
                            str(name): int(str(amount))
                            for name, amount in ref.extra
                        }
                    return ref.item, grade, investments, bool(ref.grade)
        try:
            explicit = False
            if len(parts) in {2, 5}:
                identifier, grade_word, tail = parts[0], parts[1], parts[2:]
                explicit = True
            elif len(parts) in {1, 4}:
                prefix, identifier = self._split_prefix(parts[0])
                grade_word, tail = prefix or "黄品", parts[1:]
                explicit = bool(prefix)
            else:
                raise ValueError
            grade = self.grade_prefix(grade_word)
        except Exception as exc:
            raise ValueError("炼阵格式") from exc
        investments = None
        if tail:
            if grade != "圣品":
                raise ValueError(
                    "黄品、玄品、地品、天品按固定配方炼制，不能追加兽宝、灵矿、灵植三数；圣品才可追加"
                )
            investments = dict(
                zip(
                    ("兽宝", "灵矿", "灵植"),
                    (int(value) for value in tail),
                    strict=True,
                )
            )
            if any(value < 1 for value in investments.values()):
                raise ValueError("圣品三相投入必须是正整数")
        return identifier, grade, investments, explicit

    def _split_prefix(self, head: str) -> tuple[str, str]:
        for length in (2, 1):
            if len(head) > length:
                candidate = head[:length]
                try:
                    self.grade_prefix(candidate)
                    return candidate, head[length:]
                except Exception:
                    continue
        return "", head

    async def overview(self, user_id: str, page: int = 1) -> FormationOverview:
        return await self._call(self._formation.overview(user_id, page))

    async def preview(self, user_id: str, identifier: str, grade: str, investments: Mapping[str, int] | None=None) -> FormationPreview:
        return await self._call(self._formation.preview(user_id, identifier, grade, investments))

    async def form(self, user_id: str, request_id: str, identifier: str, grade: str, investments: Mapping[str, int] | None=None) -> FormationResult:
        return await self._call(self._formation.form(user_id, request_id, identifier, grade, investments))


    def format_actions(self) -> tuple[object, ...]:
        """格式与提示类回执的动作：只给「查看帮助」——完整用法在帮助组件里。"""

        return actions(self._buttons, "格式", set())
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
