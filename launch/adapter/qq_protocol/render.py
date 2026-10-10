"""公共消息协议到 QQ 原生发送协议的翻译。"""

from __future__ import annotations

from urllib.parse import quote

from message import Action, DocumentMessage, ImageMessage, coerce_message
from message.renderers.markdown import render_markdown, render_rich_markdown
from message.renderers.plain_text import render_rich_text
from message.schema import CommandLink

from . import payload as qq_payload
from .keyboard import validate_keyboard

MAX_BUTTONS = 25
MAX_BUTTONS_PER_ROW = 3


def render_qq_message(value: object) -> object:
    """识别公共消息对象；其它值保留给 QQ 原生协议兼容路径。"""

    message = coerce_message(value)
    if isinstance(message, DocumentMessage):
        content = render_markdown(message.document, command_renderer=_command_link)
        keyboard = (
            _keyboard(message.document.actions) if message.document.actions else None
        )
        return qq_payload.markdown(content, keyboard=keyboard)
    if isinstance(message, ImageMessage):
        return qq_payload.image(
            message.image, content=render_rich_text(message.caption) or " "
        )
    return value


def _command_link(
    command: CommandLink,
    line_size: str = "body",
    default_tone: str = "",
    force_formula: bool = False,
) -> str:
    label = render_rich_markdown(
        command.label,
        line_size=line_size,
        default_tone=default_tone,
        force_formula=force_formula,
    )
    encoded = quote(command.command, safe="")
    submit = "true" if command.submit else "false"
    reply = "true" if command.reply else "false"
    return f"[{label}](mqqapi://aio/inlinecmd?command={encoded}&enter={submit}&reply={reply})"


def _keyboard(actions: tuple[Action, ...]) -> dict:
    if len(actions) > MAX_BUTTONS:
        raise ValueError(f"QQ keyboard 最多支持 {MAX_BUTTONS} 个按钮")
    buttons = [_button(action) for action in actions]
    rows = [
        {"buttons": buttons[start : start + MAX_BUTTONS_PER_ROW]}
        for start in range(0, len(buttons), MAX_BUTTONS_PER_ROW)
    ]
    return validate_keyboard({"content": {"rows": rows}})


def _button(action: Action) -> dict:
    action_type = {
        "link": 0,
        "callback": 1,
        "send": 2,
        "fill": 2,
    }[action.behavior]
    permission_type = {
        "specified": 0,
        "admins": 1,
        "everyone": 2,
    }[action.permission]
    permission: dict = {"type": permission_type}
    if action.permission == "specified":
        permission["specify_user_ids"] = list(action.specified_user_ids)

    native_action: dict = {
        "type": action_type,
        "data": action.data,
        "permission": permission,
        "unsupport_tips": "当前客户端不支持该操作.",
    }
    if action_type == 2:
        native_action["enter"] = action.behavior == "send"
        native_action["reply"] = action.reply

    return {
        "id": action.action_id,
        "render_data": {
            "label": action.label,
            "visited_label": action.visited_label or action.label,
            "style": 1 if action.style == "primary" else 0,
        },
        "action": native_action,
    }
