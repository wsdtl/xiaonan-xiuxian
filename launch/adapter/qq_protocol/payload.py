"""QQ 驱动器内部发送协议构造函数。"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

QqReplyKind = Literal["text", "markdown", "ark", "embed", "media", "image", "raw"]


class QqReplyPayload(TypedDict, total=False):
    """QQ 驱动器发送协议对象。

    这个对象属于 QQ 驱动器边界，负责表达 QQ 官方发送消息能力；
    业务组件不应该直接拼 OpenAPI payload。
    """

    kind: QqReplyKind
    content: str
    markdown: dict[str, Any]
    keyboard: dict[str, Any]
    ark: dict[str, Any]
    embed: dict[str, Any]
    media: dict[str, Any]
    image: Any
    payload: dict[str, Any]
    message_reference: dict[str, Any]
    msg_seq: int


def text(content: object, **extra: Any) -> QqReplyPayload:
    """构造 QQ 文本消息。"""

    return _reply("text", content=str(content or ""), **extra)


def markdown(
    content: object = "",
    *,
    keyboard: dict[str, Any] | None = None,
    custom_template_id: str | None = None,
    params: list[dict[str, Any]] | None = None,
    markdown_data: dict[str, Any] | None = None,
    **extra: Any,
) -> QqReplyPayload:
    """构造 QQ Markdown 消息。"""

    markdown_obj = dict(markdown_data or {})
    content_text = str(content or "")
    if content_text:
        markdown_obj["content"] = content_text
    if custom_template_id:
        markdown_obj["custom_template_id"] = str(custom_template_id)
    if params is not None:
        markdown_obj["params"] = params

    payload = _reply("markdown", markdown=markdown_obj, **extra)
    # 不再附带纯文本 content：官方要求「传了 markdown 后 content 必须为空」
    # （见 v2 发送单聊/群聊消息接口表）。此前两个字段带同一份正文，
    # 桌面端客户端可能因此多渲染出一块空白框（手机端忽略，所以只在电脑端可见）。
    if keyboard is not None:
        payload["keyboard"] = keyboard
    return payload

def ark(ark_data: dict[str, Any], *, content: object = " ", **extra: Any) -> QqReplyPayload:
    """构造 QQ Ark 消息。"""

    return _reply("ark", content=str(content or " "), ark=dict(ark_data or {}), **extra)


def embed(embed_data: dict[str, Any], *, content: object = " ", **extra: Any) -> QqReplyPayload:
    """构造 QQ Embed 消息。"""

    return _reply("embed", content=str(content or " "), embed=dict(embed_data or {}), **extra)


def media(
    media_data: dict[str, Any] | str,
    *,
    content: object = " ",
    **extra: Any,
) -> QqReplyPayload:
    """构造 QQ 富媒体消息，media_data 可以是 file_info 字符串或 media 对象。"""

    media_obj = {"file_info": media_data} if isinstance(media_data, str) else dict(media_data or {})
    return _reply("media", content=str(content or " "), media=media_obj, **extra)


def image(image_data: Any, *, content: object = " ", **extra: Any) -> QqReplyPayload:
    """构造 QQ 图片消息；发送前由 QQ manager 上传为 media file_info。"""

    return _reply("image", content=str(content or " "), image=image_data, **extra)


def raw(payload: dict[str, Any]) -> QqReplyPayload:
    """构造 QQ 原始 OpenAPI payload，用于驱动器调试或官方新增能力。"""

    return _reply("raw", payload=dict(payload or {}))


def payload_text(payload: object) -> str:
    """从 QQ 载荷里取正文：markdown 消息取 markdown.content，其余取 content。

    官方要求「传了 markdown 后 content 必须为空」，所以 markdown 消息的正文只在
    markdown.content 里；各处读正文统一走这一口，免得各写一套、形态一变就炸。
    """

    if isinstance(payload, dict):
        markdown = payload.get("markdown")
        if isinstance(markdown, dict) and markdown.get("content"):
            return str(markdown["content"])
        if payload.get("content"):
            return str(payload["content"])
        return ""
    return "" if payload is None else str(payload)


def _reply(kind: QqReplyKind, **fields: Any) -> QqReplyPayload:
    payload: QqReplyPayload = {"kind": kind}
    for key, value in fields.items():
        if value is not None:
            payload[key] = value
    return payload
