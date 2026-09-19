"""查看回复使用的文本与数值格式化辅助。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def _plain_value(value: object) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, Mapping):
        return "、".join(f"{key}{_plain_value(child)}" for key, child in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return "、".join(_plain_value(child) for child in value)
    return str(value)


def _number(value: object) -> float:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else 0.0
    )


def _display_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def _display_name(value: object) -> str:
    text = str(value or "")
    return text[6:] if len(text) > 6 and text[:6].isdigit() else text


def _signed(method: object, value: object) -> str:
    sign = "+" if method == "增加" else "-" if method == "减少" else ""
    return f"{sign}{value if value is not None else ''}"


def _related_name(value: object, related: Mapping[str, object]) -> str:
    key = str(value or "").strip()
    if not key:
        return ""
    detail = related.get(key)
    return str(detail.name) if detail is not None else key
