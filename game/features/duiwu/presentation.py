"""读取队伍展示 JSON。"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService
from game.features.presentation import (
    BUTTON_KEYS_WITHOUT_CONDITION,
    project_buttons,
    require_mapping,
)

from .contracts import TeamAction, TeamCopy

_TEXT_SECTIONS = frozenset({"图标", "格式", "查看", "结果", "错误"})
_PAGES = frozenset({"未组队", "待处理邀请", "队长", "队员"})


def load_presentation(
    data: JsonDataService,
) -> tuple[TeamCopy, tuple[Mapping[str, str], ...]]:
    raw_text = data.dataset("队伍展示").get("文本")
    if not isinstance(raw_text, Mapping):
        raise JsonDataError("队伍展示缺少文本.json")
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
        raise JsonDataError("队伍文本必须完整包含图标、格式、查看、结果、错误")
    buttons = project_buttons(
        data.dataset("队伍按钮").get("按钮"),
        label="队伍按钮",
        keys=BUTTON_KEYS_WITHOUT_CONDITION,
    )
    identities = tuple(button["编号"] for button in buttons)
    if len(identities) != len(set(identities)):
        raise JsonDataError("队伍按钮编号不能重复")
    if any(button["页面"] not in _PAGES for button in buttons):
        raise JsonDataError("队伍按钮使用了未知页面")
    return TeamCopy(text), buttons


def actions(
    buttons: tuple[Mapping[str, str], ...], page: str
) -> tuple[TeamAction, ...]:
    return tuple(
        TeamAction(
            button["编号"],
            button["名称"],
            button["命令"],
            button["行为"],
            button["样式"],
        )
        for button in buttons
        if button["页面"] == page
    )


__all__ = ["actions", "load_presentation"]
