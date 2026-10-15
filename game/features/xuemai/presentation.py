"""血脉展示的装载（复用 game/features/presentation.py 的共享骨架）。"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from game.core.data import JsonDataError, mapping as require_mapping, strict_text as _text
from game.features.presentation import (
    BUTTON_KEYS_WITHOUT_CONDITION,
    Button,
    project_unique_buttons,
)

from .contracts import GenealogyCopy

#: 血脉展示的页面白名单（第一版只有族谱页）。
PAGES = frozenset({"族谱", "传位", "错误", "命令"})


def load_xuemai_presentation(
    dataset: Mapping[str, object],
) -> tuple[GenealogyCopy, tuple[Button, ...]]:
    """装载血脉展示：校验字段集，读出文本、图标与按钮。"""

    if set(dataset) != {"文本", "图标", "血脉"}:
        raise JsonDataError("血脉展示必须包含文本、图标和血脉按钮")

    text_value = require_mapping(dataset["文本"], "玩法/血脉/展示/规则/文本.json")
    icons_value = require_mapping(dataset["图标"], "玩法/血脉/展示/规则/图标.json")

    text: dict[str, Mapping[str, str]] = {}
    for page, row in text_value.items():
        key = str(page)
        if key not in PAGES:
            raise JsonDataError(f"血脉展示出现未知页面：{key}")
        cells = require_mapping(row, f"血脉文本.{key}")
        text[key] = MappingProxyType(
            {str(name): _text(value, f"血脉文本.{key}.{name}") for name, value in cells.items()}
        )

    icons = MappingProxyType(
        {str(name): _text(value, f"血脉图标.{name}") for name, value in icons_value.items()}
    )

    buttons = project_unique_buttons(
        dataset["血脉"],
        label="玩法/血脉/展示/按钮/血脉.json",
        keys=BUTTON_KEYS_WITHOUT_CONDITION,
    )
    return GenealogyCopy(text=MappingProxyType(text), icons=icons), buttons