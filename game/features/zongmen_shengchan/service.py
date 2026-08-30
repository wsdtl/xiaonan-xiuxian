"""宗门资源生产入口编排与展示文本读取。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService
from game.core.sect_production import SectProductionError, SectProductionService

from .contracts import SectProductionAction


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
        raw = self._data.dataset("宗门生产展示").get("文本")
        if not isinstance(raw, Mapping):
            raise JsonDataError("宗门生产展示缺少文本.json")
        self._copy = raw
        rows = self._data.dataset("宗门生产按钮").get("按钮")
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise JsonDataError("宗门生产按钮必须是字典列表")
        self._buttons = tuple(
            MappingProxyType(
                {
                    key: str(_mapping(row, "宗门生产按钮[]").get(key) or "").strip()
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

    def actions(self, view) -> tuple[SectProductionAction, ...]:
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

    async def view(self, kind: str, user_id: str):
        try:
            return await self._production.view(kind, user_id)
        except SectProductionError as exc:
            raise SectProductionFeatureError(str(exc)) from exc

    async def collect(self, kind: str, user_id: str, request_id: str):
        try:
            current = await self._production.view(kind, user_id)
            if not current.started:
                raise SectProductionFeatureError(
                    f"{kind}尚未开启，请先发送：{kind} 开启"
                )
            return await self._production.collect(kind, user_id, request_id)
        except SectProductionError as exc:
            raise SectProductionFeatureError(str(exc)) from exc

    async def start(self, kind: str, user_id: str, request_id: str):
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


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return value


def _validate_buttons(buttons: tuple[Mapping[str, str], ...]) -> None:
    if any(button["页面"] != "查看" for button in buttons):
        raise JsonDataError("宗门生产按钮只能用于查看页")
    expected = {
        (facility, condition)
        for facility in ("灵脉", "灵田")
        for condition in ("尚未开始", "已经开始")
    }
    if {(button["设施"], button["条件"]) for button in buttons} != expected:
        raise JsonDataError("宗门生产按钮必须为灵脉和灵田分别定义开启与收取条件")
    if any(
        not button[key]
        for button in buttons
        for key in ("设施", "编号", "名称", "命令", "行为", "样式")
    ):
        raise JsonDataError("宗门生产按钮字段不能为空")


__all__ = ["SectProductionFeature", "SectProductionFeatureError"]
