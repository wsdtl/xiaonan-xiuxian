"""读取托管展示 JSON。"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService
from game.features.presentation import require_mapping

from .contracts import HostingAction, HostingCopy

_TEXT_SECTIONS = frozenset({"图标", "结果", "错误"})


def load_presentation(data: JsonDataService) -> HostingCopy:
    raw = data.dataset("托管展示").get("文本")
    buttons = raw.get("按钮") or () if isinstance(raw, Mapping) else ()
    raw = {key: value for key, value in raw.items() if key != "按钮"} if isinstance(raw, Mapping) else raw
    if not isinstance(raw, Mapping):
        raise JsonDataError("托管展示缺少文本.json")
    text = MappingProxyType(
        {
            str(section): MappingProxyType(
                {
                    str(key): str(value)
                    for key, value in require_mapping(value, str(section)).items()
                }
            )
            for section, value in raw.items()
        }
    )
    if set(text) != _TEXT_SECTIONS:
        raise JsonDataError("托管文本必须完整包含图标、结果、错误")
    actions = tuple(
        HostingAction(
            str(row["编号"]), str(row["名称"]), str(row["命令"]),
            str(row["行为"]), str(row["样式"]),
        )
        for row in buttons
        if isinstance(row, Mapping)
    )
    return HostingCopy(text, actions)


__all__ = ["load_presentation"]
