"""读取山门展示 JSON。"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService
from game.features.presentation import (
    POSITIONED_BUTTON_KEYS,
    project_buttons,
    require_mapping,
)

from .contracts import GateAction, GateCopy

_TEXT_SECTIONS = frozenset({"图标", "结果", "错误"})
_POSITIONS = frozenset({"山门入口", "宗门洞天"})


def load_presentation(
    data: JsonDataService,
) -> tuple[GateCopy, tuple[Mapping[str, str], ...]]:
    raw_text = data.dataset("山门展示").get("文本")
    if not isinstance(raw_text, Mapping):
        raise JsonDataError("山门展示缺少文本.json")
    text = MappingProxyType(
        {
            str(section): MappingProxyType(
                {
                    str(key): str(value)
                    for key, value in require_mapping(raw, str(section)).items()
                }
            )
            for section, raw in raw_text.items()
        }
    )
    if set(text) != _TEXT_SECTIONS:
        raise JsonDataError("山门文本必须完整包含图标、结果、错误")
    buttons = project_buttons(
        data.dataset("山门按钮").get("按钮"),
        label="山门按钮",
        keys=POSITIONED_BUTTON_KEYS,
    )
    if len({button["编号"] for button in buttons}) != len(buttons):
        raise JsonDataError("山门按钮编号不能重复")
    if any(button["位置"] not in _POSITIONS for button in buttons):
        raise JsonDataError("山门按钮位置无效")
    return GateCopy(text), buttons


def actions(
    buttons: tuple[Mapping[str, str], ...], position: str
) -> tuple[GateAction, ...]:
    return tuple(
        GateAction(
            button["编号"],
            button["名称"],
            button["命令"],
            button["行为"],
            button["样式"],
        )
        for button in buttons
        if button["位置"] == position
    )


__all__ = ["actions", "load_presentation"]
