"""读取闭关展示 JSON 并生成强业务联动动作。"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService
from game.features.presentation import project_buttons, require_mapping

from .contracts import RetreatAction, RetreatCopy

_PAGES = frozenset({"开始", "进度", "总结"})


def load_presentation(
    data: JsonDataService,
) -> tuple[RetreatCopy, tuple[Mapping[str, str], ...]]:
    raw_text = data.dataset("闭关展示").get("文本")
    if not isinstance(raw_text, Mapping):
        raise JsonDataError("闭关展示缺少文本.json")
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
    buttons = project_buttons(data.dataset("闭关按钮").get("按钮"), label="闭关按钮")
    if any(button["页面"] not in _PAGES for button in buttons):
        raise JsonDataError("闭关按钮使用了未知页面")
    if len({button["编号"] for button in buttons}) != len(buttons):
        raise JsonDataError("闭关按钮编号不能重复")
    return RetreatCopy(text), buttons


def actions(
    buttons: tuple[Mapping[str, str], ...],
    page: str,
    conditions: set[str],
    variables: Mapping[str, object] | None = None,
) -> tuple[RetreatAction, ...]:
    values = {str(key): str(value) for key, value in (variables or {}).items()}
    return tuple(
        RetreatAction(
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