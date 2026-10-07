"""读取采药展示 JSON 并生成强业务联动动作。"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService
from game.features.presentation import project_buttons, require_mapping, validate_page_buttons, validate_page_buttons

from .contracts import HerbGatheringAction, HerbGatheringCopy


def load_presentation(
    data: JsonDataService,
) -> tuple[HerbGatheringCopy, tuple[Mapping[str, str], ...]]:
    raw_text = data.dataset("采药展示").get("文本")
    if not isinstance(raw_text, Mapping):
        raise JsonDataError("采药展示缺少文本.json")
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
    buttons = project_buttons(
        data.dataset("采药按钮").get("按钮"),
        label="采药按钮",
    )
    validate_page_buttons(buttons, "采药")
    return HerbGatheringCopy(text), buttons


def actions(
    buttons: tuple[Mapping[str, str], ...],
    page: str,
    conditions: set[str],
    variables: Mapping[str, object] | None = None,
) -> tuple[HerbGatheringAction, ...]:
    values = {str(key): str(value) for key, value in (variables or {}).items()}
    return tuple(
        HerbGatheringAction(
            button["编号"],
            button["名称"],
            button["命令"].format_map(values),
            button["行为"],
            button["样式"],
        )
        for button in buttons
        if button["页面"] == page
        and (not button["条件"] or button["条件"] in conditions)
    )


__all__ = ["actions", "load_presentation"]
