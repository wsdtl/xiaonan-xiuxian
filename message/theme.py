"""公共消息的唯一视觉主题。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, cast

LineSize = Literal["body", "caption"]


@dataclass(frozen=True)
class ToneStyle:
    """一项语义色；空字符串表示保留客户端默认正文色。"""

    color: str = ""


_TONES = {
    # 标题、栏目和普通说明不再染色，层级交给 Markdown 与字号表达。
    "title": ToneStyle(),
    "section": ToneStyle(),
    "label": ToneStyle(),
    "muted": ToneStyle(),
    # 可点击对象统一使用一条引导色，避免按类别铺开彩虹色。
    "emphasis": ToneStyle("#3B5B7A"),
    "positive": ToneStyle("#27AE60"),
    "warning": ToneStyle("#C47F00"),
    "danger": ToneStyle("#C0392B"),
    # 信息状态不承担告警职责，保持正文色，避免把状态栏做成色条。
    "info": ToneStyle(),
    "mystic": ToneStyle("#3B5B7A"),
    "companion": ToneStyle("#3B5B7A"),
    "health": ToneStyle("#C0392B"),
    "spirit": ToneStyle("#3B5B7A"),
    "cultivation": ToneStyle("#3B5B7A"),
    "metal": ToneStyle("#3B5B7A"),
    "wood": ToneStyle("#3B5B7A"),
    "water": ToneStyle("#3B5B7A"),
    "fire": ToneStyle("#C0392B"),
    "earth": ToneStyle("#3B5B7A"),
    "formless": ToneStyle("#3B5B7A"),
}
TONES = MappingProxyType(_TONES)

TITLE_SIZE_COMMAND = "large"
BODY_SIZE_COMMAND = "normalsize"
CAPTION_SIZE_COMMAND = "small"
PROGRESS_EMPTY_COLOR = "#B0B0B0"
PROGRESS_FILLED_COLOR = "#3B5B7A"
PROGRESS_SEGMENTS = 5
PROGRESS_FILLED_GLYPH = "▰"
PROGRESS_EMPTY_GLYPH = "▱"


def normalize_tone(value: object, *, default: str = "") -> str:
    tone = str(value or default).strip().lower()
    if not tone:
        return ""
    if tone not in TONES:
        raise ValueError(f"未知消息语义色：{tone}")
    return tone


def tone_style(value: object, *, default: str = "") -> ToneStyle:
    tone = normalize_tone(value, default=default)
    if not tone:
        raise ValueError("消息语义色不能为空")
    return TONES[tone]


def normalize_line_size(value: object) -> LineSize:
    size = str(value or "body").strip().lower()
    if size not in {"body", "caption"}:
        raise ValueError(f"未知消息行字号：{size}")
    return cast(LineSize, size)


__all__ = [
    "BODY_SIZE_COMMAND",
    "CAPTION_SIZE_COMMAND",
    "PROGRESS_EMPTY_COLOR",
    "PROGRESS_EMPTY_GLYPH",
    "PROGRESS_FILLED_COLOR",
    "PROGRESS_FILLED_GLYPH",
    "PROGRESS_SEGMENTS",
    "TITLE_SIZE_COMMAND",
    "TONES",
    "LineSize",
    "ToneStyle",
    "normalize_line_size",
    "normalize_tone",
    "tone_style",
]
