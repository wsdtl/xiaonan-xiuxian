"""宗门资源生产入口编排与展示文本读取。"""

from __future__ import annotations

from game.core.sect_production import (
    SectProductionView,
    SectProductionResult,
    SectProductionError,
    SectProductionService,
)

from collections.abc import Mapping, Sequence
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService
from game.features.presentation import require_mapping

from .contracts import SectProductionAction, SectProductionEntry


class SectProductionFeatureError(RuntimeError):
    """宗门资源生产玩法无法完成当前请求。"""


class SectProductionFeature:
    def __init__(
        self, data: JsonDataService, production: SectProductionService
    ) -> None:
        self._data = data
        self._production = production
        self._copy: Mapping[str, Mapping[str, str]] | None = None
        self._buttons: tuple[Mapping[str, str], ...] = ()

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("宗门资源生产玩法已经初始化")
        common = self._data.dataset("产出通用文案").get("产出通用")
        if not isinstance(common, Mapping):
            raise JsonDataError("产出展示缺少通用.json")
        raw = {"通用": common.get("通用")}
        texts = {
            "灵脉": self._data.dataset("灵脉页面文案").get("文本"),
            "灵田": self._data.dataset("灵田页面文案").get("文本"),
        }
        button_rows = {
            "灵脉": self._data.dataset("灵脉页面按钮").get("按钮") or (),
            "灵田": self._data.dataset("灵田页面按钮").get("按钮") or (),
        }
        rows: list[Mapping[str, object]] = []
        for name in ("灵脉", "灵田"):
            section = texts[name]
            if not isinstance(section, Mapping):
                raise JsonDataError(f"{name}展示缺少文本.json")
            raw[name] = section
            buttons = button_rows[name]
            if not isinstance(buttons, Sequence) or isinstance(buttons, (str, bytes)):
                raise JsonDataError(f"{name}按钮必须是字典列表")
            rows.extend(row for row in buttons if isinstance(row, Mapping))
        self._copy = raw
        self._buttons = tuple(
            MappingProxyType(
                {
                    key: str(require_mapping(row, "产出按钮[]").get(key) or "").strip()
                    for key in (
                        "页面",
                        "设施",
                        "条件",
                        "编号",
                        "名称",
                        "命令",
                        "行为",
                        "样式",
                    )
                }
            )
            for row in rows
        )
        _validate_buttons(self._buttons)

    def copy(self) -> Mapping[str, Mapping[str, str]]:
        if self._copy is None:
            raise RuntimeError("宗门资源生产玩法尚未初始化")
        return self._copy

    def terrain_options(self, kind: str) -> tuple[str, ...]:
        """该设施可选的地形（不需要宗门身份，页面据此把菜单摆出来）。"""

        for facility in self._production.status().facilities:
            if facility.kind == str(kind or '').strip():
                return tuple(getattr(facility, 'terrain_options', ()) or ())
        return ()

    def actions(self, view: SectProductionView) -> tuple[SectProductionAction, ...]:
        if not view.can_collect or (view.started and view.pending_cycles == 0):
            return ()
        condition = "已经开始" if view.started else "尚未开始"
        return tuple(
            SectProductionAction(
                button["编号"],
                button["名称"],
                button["命令"],
                button["行为"],
                button["样式"],
            )
            for button in self._buttons
            if button["页面"] == "查看"
            and button["设施"] == view.facility.kind
            and button["条件"] == condition
        )

    async def enter(
        self, kind: str, user_id: str, request_id: str, query: str
    ) -> SectProductionEntry:
        """解析资源设施根命令；分支与参数合规只由本玩法判定。"""

        args = str(query or "").split()
        if not args:
            return SectProductionEntry(
                "view", view=await self.view(kind, user_id)
            )
        if args == ["开启"]:
            return SectProductionEntry(
                "started", result=await self.start(kind, user_id, request_id)
            )
        if args == ["收取"]:
            return SectProductionEntry(
                "collected", result=await self.collect(kind, user_id, request_id)
            )
        if args[0] == "选地形" and len(args) <= 2:
            if len(args) == 1:
                return SectProductionEntry(
                    "terrains", view=await self.view(kind, user_id)
                )
            return SectProductionEntry(
                "placed",
                view=await self.select_terrain(kind, user_id, request_id, args[1]),
            )
        if args == ["清地形"]:
            return SectProductionEntry(
                "placed",
                view=await self.clear_terrain(kind, user_id, request_id),
            )
        raise SectProductionFeatureError(f"格式：{self._usage(kind)}")

    def _usage(self, kind: str) -> str:
        return (
            f"{kind}、{kind} 开启、{kind} 收取、"
            f"{kind} 选地形 [地形名] 或 {kind} 清地形"
        )

    async def view(self, kind: str, user_id: str) -> SectProductionView:
        try:
            return await self._production.view(kind, user_id)
        except SectProductionError as exc:
            raise SectProductionFeatureError(str(exc)) from exc

    async def collect(self, kind: str, user_id: str, request_id: str) -> SectProductionResult:
        try:
            current = await self._production.view(kind, user_id)
            if not current.started:
                raise SectProductionFeatureError(
                    f"{kind}尚未开启，请先发送：{kind} 开启"
                )
            return await self._production.collect(kind, user_id, request_id)
        except SectProductionError as exc:
            raise SectProductionFeatureError(str(exc)) from exc

    async def start(self, kind: str, user_id: str, request_id: str) -> SectProductionResult:
        try:
            current = await self._production.view(kind, user_id)
            if current.started:
                raise SectProductionFeatureError(f"{kind}已经开启，无需重复开启")
            result = await self._production.collect(kind, user_id, request_id)
            if not result.newly_started:
                raise SectProductionFeatureError(f"{kind}刚刚由其他人开启，请重新查看")
            return result
        except SectProductionError as exc:
            raise SectProductionFeatureError(str(exc)) from exc

    async def select_terrain(
        self, kind: str, user_id: str, request_id: str, terrain: str
    ) -> SectProductionView:
        try:
            return await self._production.select_terrain(
                kind, user_id, request_id, terrain
            )
        except SectProductionError as exc:
            raise SectProductionFeatureError(str(exc)) from exc

    async def clear_terrain(self, kind: str, user_id: str, request_id: str) -> SectProductionView:
        try:
            return await self._production.clear_terrain(kind, user_id, request_id)
        except SectProductionError as exc:
            raise SectProductionFeatureError(str(exc)) from exc


def _validate_buttons(buttons: tuple[Mapping[str, str], ...]) -> None:
    if any(button["页面"] != "查看" for button in buttons):
        raise JsonDataError("产出按钮只能用于查看页")
    expected = {
        (facility, condition)
        for facility in ("灵脉", "灵田")
        for condition in ("尚未开始", "已经开始")
    }
    if {(button["设施"], button["条件"]) for button in buttons} != expected:
        raise JsonDataError("产出按钮必须为灵脉和灵田分别定义开启与收取条件")
    if any(
        not button[key]
        for button in buttons
        for key in ("设施", "编号", "名称", "命令", "行为", "样式")
    ):
        raise JsonDataError("产出按钮字段不能为空")


__all__ = ["SectProductionFeature", "SectProductionFeatureError"]
