"""读取探险展示 JSON 并生成强业务联动动作。"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService
from game.features.presentation import project_buttons, require_mapping

from .contracts import ExplorationAction, ExplorationCopy


def load_presentation(
    data: JsonDataService,
) -> tuple[ExplorationCopy, tuple[Mapping[str, str], ...]]:
    raw_text = data.dataset("探险展示").get("文本")
    if not isinstance(raw_text, Mapping):
        raise JsonDataError("探险展示缺少文本.json")
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
        data.dataset("探险按钮").get("按钮"),
        label="探险按钮",
    )
    return ExplorationCopy(text), buttons


def actions(
    buttons: tuple[Mapping[str, str], ...],
    page: str,
    conditions: set[str],
    variables: Mapping[str, object] | None = None,
) -> tuple[ExplorationAction, ...]:
    values = {str(key): str(value) for key, value in (variables or {}).items()}
    return tuple(
        ExplorationAction(
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
