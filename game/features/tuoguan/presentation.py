"""读取托管展示 JSON。"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService
from game.features.presentation import require_mapping

from .contracts import HostingCopy

_TEXT_SECTIONS = frozenset({"图标", "结果", "错误"})


def load_presentation(data: JsonDataService) -> HostingCopy:
    raw = data.dataset("托管展示").get("文本")
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
    return HostingCopy(text)


__all__ = ["load_presentation"]
