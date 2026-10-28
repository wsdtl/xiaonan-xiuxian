"""宗门战玩法入口与展示数据解释。"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService
from game.core.sect_assets import SectAssetError
from game.core.sect_war import (
    SectWarError,
    SectWarHistoryPage,
    SectWarService,
    SectWarView,
)
from game.features.presentation import require_mapping


@dataclass(frozen=True)
class SectWarAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


class SectWarFeature:
    def __init__(self, data: JsonDataService, war: SectWarService) -> None:
        self._data = data
        self._war = war
        self._text: Mapping[str, Mapping[str, str]] | None = None
        self._buttons: tuple[Mapping[str, str], ...] = ()

    def initialize(self) -> None:
        if self._text is not None:
            raise RuntimeError("宗门战玩法已经初始化")
        if not self._war.status().initialized:
            raise RuntimeError("宗门战核心必须先于玩法微服务启动")
        raw = self._data.dataset("宗门战页面文案").get("文本")
        if not isinstance(raw, Mapping):
            raise JsonDataError("宗门战展示缺少文本.json")
        text = MappingProxyType(
            {
                str(section): MappingProxyType(
                    {
                        str(key): str(value)
                        for key, value in require_mapping(values, str(section)).items()
                    }
                )
                for section, values in raw.items()
            }
        )
        required = {"图标", "查看", "格式", "结果", "状态", "错误", "介绍"}
        if set(text) != required:
            raise JsonDataError("宗门战文本必须完整包含图标、查看、格式、结果、状态、错误")
        raw_buttons = self._data.dataset("宗门战页面按钮").get("按钮")
        if not isinstance(raw_buttons, Sequence) or isinstance(raw_buttons, (str, bytes)):
            raise JsonDataError("宗门战按钮必须是字典列表")
        buttons = tuple(
            MappingProxyType(
                {
                    key: str(require_mapping(item, "宗门战按钮[]").get(key) or "").strip()
                    for key in ("状态", "编号", "名称", "命令", "行为", "样式")
                }
            )
            for item in raw_buttons
        )
        if len({button["编号"] for button in buttons}) != len(buttons):
            raise JsonDataError("宗门战按钮编号不能重复")
        self._text = text
        self._buttons = buttons

    async def challenge_from_text(
        self, user_id: str, raw_args: str, request_id: str
    ) -> SectWarView:
        """从原始约战参数取目标与押注；格式合规由本玩法判定。"""

        parts = str(raw_args or "").split()
        if len(parts) != 2 or not parts[1].isdecimal() or int(parts[1]) < 1:
            raise ValueError("约战格式")
        return await self.challenge(
            user_id, parts[0], int(parts[1]), request_id
        )

    async def current_from_text(
        self, user_id: str, war_id: str, request_id: str
    ) -> SectWarView:
        return (
            await self.view(user_id, war_id)
            if war_id
            else await self.current(user_id, request_id)
        )

    async def challenge(self, user_id: str, target: str, wager: int, request_id: str) -> SectWarView:
        return await self._pass(self._war.challenge(user_id, target, wager, request_id))

    async def accept(self, user_id: str, request_id: str) -> SectWarView:
        return await self._pass(self._war.accept_and_start(user_id, request_id))

    async def reject(self, user_id: str, request_id: str) -> SectWarView:
        return await self._pass(self._war.reject(user_id, request_id))

    async def withdraw(self, user_id: str, request_id: str) -> SectWarView:
        return await self._pass(self._war.withdraw(user_id, request_id))

    async def current(self, user_id: str, request_id: str="") -> SectWarView:
        return await self._pass(self._war.current(user_id, request_id))

    async def view(self, user_id: str, war_id: str) -> SectWarView:
        return await self._pass(self._war.view(user_id, war_id))

    def text(self, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
        if self._text is None:
            raise RuntimeError("宗门战玩法尚未初始化")
        try:
            template = self._text[section][key]
        except KeyError as exc:
            raise RuntimeError(f"宗门战展示缺少文本：{section}.{key}") from exc
        return template.format_map(values or {})

    async def _pass(self, awaitable: Awaitable[Any]) -> Any:
        """宗门公共资产的异常（如「宗门灵石不足」）在这一层翻译成宗门战自己的错误类型。

        分层规定：命令层不得导入 `game.core.*`，所以核心的异常必须在玩法层收口；
        `error()` 落不到展示键时会直接用异常自己的话，提示文案因此原样保留。
        """
        try:
            return await awaitable
        except SectAssetError as exc:
            raise SectWarError(str(exc)) from exc

    def error(self, error: SectWarError) -> str:
        if self._text is not None and error.code in self._text["错误"]:
            return self._text["错误"][error.code]
        return str(error)

    def format_actions(self, status: str) -> tuple[SectWarAction, ...]:
        """格式与提示类回执的动作：只给该命令的「查看帮助」。"""

        return self.actions(status)


    def actions(self, status: str) -> tuple[SectWarAction, ...]:
        return tuple(
            SectWarAction(
                button["编号"],
                button["名称"],
                button["命令"],
                button["行为"],
                button["样式"],
            )
            for button in self._buttons
            if button["状态"] == status
        )


__all__ = [
    "SectWarAction",
    "SectWarError",
    "SectWarFeature",
    "SectWarHistoryPage",
    "SectWarView",
]
