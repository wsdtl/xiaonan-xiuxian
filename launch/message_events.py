"""适配器消息事件总线。

这里是框架层的中立观察口：QQ 或未来驱动器只把“收到/发出了一条
可展示消息”发布出来，不反向依赖任何业务组件。真正的归属解析、过滤、
落库和页面展示由订阅方自己完成。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from message import (
    Action,
    CommandLink,
    DocumentMessage,
    ImageMessage,
    RenderedMessage,
    coerce_message,
    render_local_message,
)
from message.renderers.markdown import render_markdown, render_rich_markdown
from message.renderers.plain_text import render_rich_text

from .log import C, logger


@dataclass(frozen=True)
class MessageInteraction:
    """一项可由其它驱动器重新呈现的协议中立交互。"""

    kind: str
    action_id: str
    label: str
    data: str
    behavior: str
    style: str = "primary"
    permission: str = "everyone"
    specified_user_ids: tuple[str, ...] = ()
    reply: bool = False
    submit: bool = True


@dataclass(frozen=True)
class MessageEvent:
    """一条驱动器收发消息的完整可展示事实。"""

    direction: str
    adapter: str
    request_id: str
    user_id: str
    message_type: str
    content: str
    sender_name: str = ""
    image: object = ""
    interactions: tuple[MessageInteraction, ...] = ()


@dataclass(frozen=True)
class MessageSnapshot:
    """从业务消息提取出的正文、媒体和交互语义。"""

    message_type: str
    content: str
    image: object = ""
    interactions: tuple[MessageInteraction, ...] = ()


MessageEventListener = Callable[[MessageEvent], Awaitable[None] | None]
_LISTENERS: list[MessageEventListener] = []


def subscribe_message_events(listener: MessageEventListener) -> None:
    """订阅消息事件；同一个 listener 只登记一次。"""

    if listener not in _LISTENERS:
        _LISTENERS.append(listener)


def unsubscribe_message_events(listener: MessageEventListener) -> None:
    """取消订阅消息事件。"""

    try:
        _LISTENERS.remove(listener)
    except ValueError:
        return


def emit_message_event(event: MessageEvent) -> None:
    """发布消息事件。

    订阅者异常只写日志，不影响驱动器收发。异步订阅者会被调度成后台任务，
    避免消息发送链路被展示组件拖住。
    """

    if not _LISTENERS:
        return
    for listener in tuple(_LISTENERS):
        try:
            result = listener(event)
        except Exception as exc:  # noqa: BLE001 - 订阅者异常不能影响消息收发
            logger.opt(colors=True, exception=exc).warning(C.warn("消息事件订阅者异常"))
            continue
        if inspect.isawaitable(result):
            try:
                task = asyncio.create_task(_await_listener(result))
                task.add_done_callback(_consume_listener_result)
            except RuntimeError as exc:
                logger.opt(colors=True, exception=exc).warning(
                    C.warn("消息事件异步订阅调度失败")
                )


def event_from_incoming(
    *,
    adapter: str,
    user_id: object,
    request_id: object = "",
    message_type: object = "text",
    content: object = "",
    sender_name: object = "",
) -> MessageEvent:
    """整理驱动器收到的消息事件。"""

    return MessageEvent(
        direction="incoming",
        adapter=_clean_token(adapter, "unknown"),
        request_id=_clean_token(request_id),
        user_id=_clean_token(user_id),
        message_type=_normalize_message_type(message_type),
        content=_clean_content(content),
        sender_name=_clean_token(sender_name),
    )


def event_from_outgoing(
    *,
    adapter: str,
    user_id: object,
    request_id: object = "",
    message: object = "",
) -> MessageEvent:
    """整理驱动器发出的业务回复事件。"""

    snapshot = snapshot_from_message(message)
    return MessageEvent(
        direction="outgoing",
        adapter=_clean_token(adapter, "unknown"),
        request_id=_clean_token(request_id),
        user_id=_clean_token(user_id),
        message_type=snapshot.message_type,
        content=snapshot.content,
        image=snapshot.image,
        interactions=snapshot.interactions,
    )


def display_content_from_message(message: object) -> tuple[str, str]:
    """从业务回复对象里提取适合消息流水展示的正文。

    这里只做协议中立的“取正文”：markdown 取 content，image 尽量取可访问
    地址，keyboard/buttons 不进入 content。业务层装饰由订阅组件再过滤。
    """

    snapshot = snapshot_from_message(message)
    return snapshot.message_type, snapshot.content


def snapshot_from_message(message: object) -> MessageSnapshot:
    """完整提取公共消息正文、媒体和全部交互语义。"""

    semantic = coerce_message(message)
    if isinstance(semantic, DocumentMessage):
        interactions = [
            _interaction_from_action(action) for action in semantic.document.actions
        ]

        def command_renderer(
            command: CommandLink,
            line_size: str = "body",
            default_tone: str = "",
            force_formula: bool = False,
        ) -> str:
            action_id = f"command-link-{len(interactions) + 1}"
            interactions.append(
                MessageInteraction(
                    kind="command_link",
                    action_id=action_id,
                    label=render_rich_text(command.label),
                    data=command.command,
                    behavior="send" if command.submit else "fill",
                    style="link",
                    reply=command.reply,
                    submit=command.submit,
                )
            )
            label = render_rich_markdown(
                command.label,
                line_size=line_size,
                default_tone=default_tone,
                force_formula=force_formula,
            )
            return f"[{label}](webcmd://{action_id})"

        return MessageSnapshot(
            message_type="markdown",
            content=render_markdown(
                semantic.document, command_renderer=command_renderer
            ),
            interactions=tuple(interactions),
        )
    if isinstance(semantic, ImageMessage):
        return MessageSnapshot(
            message_type="image",
            content=render_rich_text(semantic.caption),
            image=_image_reference(semantic.image),
        )

    message = render_local_message(message)
    if isinstance(message, RenderedMessage):
        interactions = tuple(
            _interaction_from_action(action) for action in message.actions
        )
        if message.kind == "image":
            return MessageSnapshot(
                "image",
                message.content,
                _image_reference(message.image),
                interactions,
            )
        return MessageSnapshot(message.kind, message.content, interactions=interactions)

    if isinstance(message, dict):
        kind = str(message.get("kind") or "").strip().lower()
        content = _message_text(message.get("content"))
        content, inline_interactions = _extract_native_command_links(content)
        interactions = (
            *_native_keyboard_interactions(message.get("keyboard")),
            *inline_interactions,
        )
        if kind == "markdown":
            return MessageSnapshot("markdown", content, interactions=interactions)
        if kind == "image":
            return MessageSnapshot(
                "image",
                content,
                _image_reference(message.get("image")),
                interactions,
            )
        if kind in {"text", "ark", "embed", "media", "raw"}:
            body = content or _message_text(message.get(kind) or message.get("payload"))
            return MessageSnapshot(kind, body, interactions=interactions)
        if "content" in message:
            return MessageSnapshot("markdown", content, interactions=interactions)
        return MessageSnapshot(
            "raw",
            json.dumps(message, ensure_ascii=False, default=str),
            interactions=interactions,
        )

    if isinstance(message, (list, tuple)):
        return MessageSnapshot(
            "text",
            "\n".join(_message_text(item) for item in message if _message_text(item)),
        )
    if message is None:
        return MessageSnapshot("unknown", "")
    return MessageSnapshot("text", str(message).strip())


def _interaction_from_action(action: Action) -> MessageInteraction:
    return MessageInteraction(
        kind="action",
        action_id=action.action_id,
        label=action.label,
        data=action.data,
        behavior=action.behavior,
        style=action.style,
        permission=action.permission,
        specified_user_ids=action.specified_user_ids,
        reply=action.reply,
        submit=action.behavior not in {"fill", "link"},
    )


def _native_keyboard_interactions(keyboard: object) -> tuple[MessageInteraction, ...]:
    if not isinstance(keyboard, dict):
        return ()
    content = (
        keyboard.get("content") if isinstance(keyboard.get("content"), dict) else {}
    )
    rows = content.get("rows") if isinstance(content.get("rows"), list) else []
    interactions: list[MessageInteraction] = []
    for row in rows:
        buttons = (
            row.get("buttons")
            if isinstance(row, dict) and isinstance(row.get("buttons"), list)
            else []
        )
        for button in buttons:
            if not isinstance(button, dict):
                continue
            action = (
                button.get("action") if isinstance(button.get("action"), dict) else {}
            )
            render_data = (
                button.get("render_data")
                if isinstance(button.get("render_data"), dict)
                else {}
            )
            data = str(action.get("data") or "").strip()
            label = str(render_data.get("label") or "").strip()
            if not data or not label:
                continue
            action_type = _safe_int(action.get("type"), 0)
            behavior = {0: "link", 1: "callback", 2: "send"}.get(
                action_type, "callback"
            )
            if action_type == 2 and action.get("enter") is False:
                behavior = "fill"
            permission_data = (
                action.get("permission")
                if isinstance(action.get("permission"), dict)
                else {}
            )
            permission = {0: "specified", 1: "admins", 2: "everyone"}.get(
                _safe_int(permission_data.get("type"), 2),
                "everyone",
            )
            interactions.append(
                MessageInteraction(
                    kind="action",
                    action_id=str(
                        button.get("id") or f"native-{len(interactions) + 1}"
                    ),
                    label=label,
                    data=data,
                    behavior=behavior,
                    style="primary"
                    if _safe_int(render_data.get("style"), 0) == 1
                    else "secondary",
                    permission=permission,
                    specified_user_ids=tuple(
                        str(value)
                        for value in permission_data.get("specify_user_ids", ())
                    ),
                    reply=bool(action.get("reply")),
                    submit=behavior not in {"fill", "link"},
                )
            )
    return tuple(interactions)


_NATIVE_COMMAND_LINK_RE = re.compile(r"\[([^\]]+)\]\((mqqapi://aio/inlinecmd\?[^)]+)\)")


def _extract_native_command_links(
    content: str,
) -> tuple[str, tuple[MessageInteraction, ...]]:
    interactions: list[MessageInteraction] = []

    def replace(match: re.Match) -> str:
        query = parse_qs(urlparse(match.group(2)).query)
        command = unquote(str((query.get("command") or [""])[0])).strip()
        if not command:
            return match.group(0)
        action_id = f"command-link-{len(interactions) + 1}"
        submit = str((query.get("enter") or ["true"])[0]).lower() == "true"
        reply = str((query.get("reply") or ["false"])[0]).lower() == "true"
        interactions.append(
            MessageInteraction(
                kind="command_link",
                action_id=action_id,
                label=match.group(1),
                data=command,
                behavior="send" if submit else "fill",
                style="link",
                reply=reply,
                submit=submit,
            )
        )
        return f"[{match.group(1)}](webcmd://{action_id})"

    return _NATIVE_COMMAND_LINK_RE.sub(replace, content), tuple(interactions)


async def _await_listener(result: Awaitable[None]) -> None:
    await result


def _consume_listener_result(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception as exc:  # noqa: BLE001 - 异步订阅者异常在任务边界消费
        logger.opt(colors=True, exception=exc).warning(C.warn("消息事件异步订阅者异常"))


def _markdown_content(message: object) -> str:
    if isinstance(message, dict):
        return _message_text(message.get("content"))
    return _message_text(message)


def _image_content(message: object) -> str:
    if isinstance(message, dict):
        for key in ("url", "src", "path", "image"):
            value = _image_content(message.get(key))
            if value and value != "〔图片〕":
                return value
        return "〔图片〕"
    if isinstance(message, str):
        return message.strip() or "〔图片〕"
    if isinstance(message, Path):
        return str(message)
    return "〔图片〕"


def _image_reference(message: object) -> object:
    """保留可由订阅组件安全物化的图片引用或字节。"""

    if isinstance(message, (bytes, bytearray, memoryview)):
        return bytes(message)
    getter = getattr(message, "getvalue", None)
    if callable(getter):
        try:
            value = getter()
        except Exception:  # noqa: BLE001 - 外部图片容器 getter 不可信
            value = None
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value)
    if isinstance(message, Path):
        return message
    if isinstance(message, dict):
        for key in ("url", "src", "path", "image"):
            if key in message:
                return _image_reference(message.get(key))
    if isinstance(message, str):
        return message.strip()
    return ""


def _message_text(message: object) -> str:
    if isinstance(message, dict):
        if "content" in message:
            return _message_text(message.get("content"))
        return json.dumps(message, ensure_ascii=False, default=str)
    if isinstance(message, (list, tuple)):
        return "\n".join(
            _message_text(item) for item in message if _message_text(item)
        ).strip()
    if message is None:
        return ""
    return str(message).strip()


def _clean_token(value: object, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _clean_content(value: object) -> str:
    return str(value or "").strip()


def _normalize_message_type(value: object) -> str:
    text = str(value or "").strip().lower()
    return (
        text
        if text in {"text", "markdown", "image", "media", "ark", "embed", "raw"}
        else "unknown"
    )


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "MessageEvent",
    "MessageInteraction",
    "MessageSnapshot",
    "display_content_from_message",
    "emit_message_event",
    "event_from_incoming",
    "event_from_outgoing",
    "snapshot_from_message",
    "subscribe_message_events",
    "unsubscribe_message_events",
]
