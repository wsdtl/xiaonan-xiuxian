"""婚配展示的装载（复用共享骨架）。"""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from game.core.data import JsonDataError, mapping as require_mapping, strict_text as _text
from game.features.presentation import BUTTON_KEYS_WITHOUT_CONDITION, Button, project_unique_buttons

from .contracts import HunpeiCopy

#: 婚配展示的页面白名单。
PAGES = frozenset({"生育", "求子", "错误", "命令"})


def load_hunpei_presentation(dataset: Mapping[str, object]) -> tuple[HunpeiCopy, tuple[Button, ...]]:
    """装载婚配展示：校验字段集，读出文本、图标与按钮。"""

    if set(dataset) != {"文本", "图标", "婚配"}:
        raise JsonDataError("婚配展示必须包含文本、图标和婚配按钮")
    text_value = require_mapping(dataset["文本"], "玩法/婚配/展示/规则/文本.json")
    icons_value = require_mapping(dataset["图标"], "玩法/婚配/展示/规则/图标.json")
    text: dict[str, Mapping[str, str]] = {}
    for page, row in text_value.items():
        key = str(page)
        if key not in PAGES:
            raise JsonDataError("婚配展示出现未知页面：%s" % key)
        cells = require_mapping(row, "婚配文本.%s" % key)
        text[key] = MappingProxyType({str(n): _text(v, "婚配文本.%s.%s" % (key, n)) for n, v in cells.items()})
    icons = MappingProxyType({str(n): _text(v, "婚配图标.%s" % n) for n, v in icons_value.items()})
    buttons = project_unique_buttons(dataset["婚配"], label="玩法/婚配/展示/按钮/婚配.json", keys=BUTTON_KEYS_WITHOUT_CONDITION)
    return HunpeiCopy(text=MappingProxyType(text), icons=icons), buttons
