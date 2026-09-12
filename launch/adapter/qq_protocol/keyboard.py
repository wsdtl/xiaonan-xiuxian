"""QQ Markdown keyboard 协议校验。

业务可以自行组织按钮，但进入 OpenAPI 前必须满足 QQ 的结构约束。这里仅校验
协议，不负责按钮文案、布局风格或业务权限。
"""

from __future__ import annotations

from typing import Any

ACTION_TYPES = {0, 1, 2, 3}
PERMISSION_TYPES = {0, 1, 2, 3}


def validate_keyboard(value: object) -> dict[str, Any]:
    """校验 keyboard 并返回原对象的浅拷贝。"""

    if not isinstance(value, dict):
        raise TypeError("QQ keyboard 必须是对象")
    if value.get("id"):
        return dict(value)

    content = value.get("content")
    if not isinstance(content, dict):
        raise TypeError("QQ keyboard 缺少 content 对象")
    rows = content.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("QQ keyboard rows 必须是非空列表")

    seen_ids: set[str] = set()
    for row_index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise TypeError(f"QQ keyboard 第 {row_index} 行必须是对象")
        buttons = row.get("buttons")
        if not isinstance(buttons, list) or not buttons:
            raise ValueError(f"QQ keyboard 第 {row_index} 行没有按钮")
        for column_index, button in enumerate(buttons, start=1):
            _validate_button(button, row_index, column_index, seen_ids)
    return dict(value)


def _validate_button(
    button: object,
    row_index: int,
    column_index: int,
    seen_ids: set[str],
) -> None:
    location = f"第 {row_index} 行第 {column_index} 个按钮"
    if not isinstance(button, dict):
        raise TypeError(f"QQ keyboard {location}必须是对象")

    button_id = str(button.get("id") or "").strip()
    if not button_id:
        raise ValueError(f"QQ keyboard {location}缺少稳定 id")
    if button_id in seen_ids:
        raise ValueError(f"QQ keyboard 按钮 id 重复：{button_id}")
    seen_ids.add(button_id)

    render_data = button.get("render_data")
    if not isinstance(render_data, dict) or not str(render_data.get("label") or "").strip():
        raise ValueError(f"QQ keyboard {location}缺少 render_data.label")

    action = button.get("action")
    if not isinstance(action, dict):
        raise TypeError(f"QQ keyboard {location}缺少 action 对象")
    action_type = _integer_field(action, "type", f"QQ keyboard {location}action.type")
    if action_type not in ACTION_TYPES:
        raise ValueError(f"QQ keyboard {location}action.type 不支持：{action_type}")
    if not str(action.get("data") or "").strip():
        raise ValueError(f"QQ keyboard {location}缺少 action.data")

    permission = action.get("permission")
    if not isinstance(permission, dict):
        raise TypeError(f"QQ keyboard {location}缺少 action.permission")
    permission_type = _integer_field(
        permission,
        "type",
        f"QQ keyboard {location}permission.type",
    )
    if permission_type not in PERMISSION_TYPES:
        raise ValueError(f"QQ keyboard {location}permission.type 不支持：{permission_type}")

    if action_type == 2:
        for field in ("enter", "reply"):
            if not isinstance(action.get(field), bool):
                raise TypeError(f"QQ keyboard {location}type=2 时 action.{field} 必须是 bool")


def _integer_field(source: dict[str, Any], field: str, label: str) -> int:
    value = source.get(field)
    if isinstance(value, bool):
        raise TypeError(f"{label} 必须是整数")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须是整数") from exc
