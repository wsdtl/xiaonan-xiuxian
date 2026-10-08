"""天道后台消息的安全 HTML 投影。"""

from __future__ import annotations

import html
import re
from dataclasses import asdict
from urllib.parse import urlparse

from .models import ConsoleFlowRecord

IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def record_payload(record: ConsoleFlowRecord) -> dict[str, object]:
    """生成历史接口和 SSE 共用的公开消息结构。"""

    return {
        "flow_id": record.flow_id,
        "direction": record.direction,
        "adapter": record.adapter,
        "request_id": record.request_id,
        "user_id": record.user_id,
        "sender_name": record.sender_name,
        "message_type": record.message_type,
        "content": record.content,
        "content_html": render_message_html(record),
        "image": record.image,
        "interactions": [asdict(interaction) for interaction in record.interactions],
        "content_truncated": record.content_truncated,
        "created_at": record.created_at,
    }


def render_message_html(record: ConsoleFlowRecord) -> str:
    """按消息类型渲染可安全插入页面的正文。"""

    if record.message_type != "markdown":
        return _plain(record.content)
    return _markdown(record.content, record.flow_id)


def _markdown(value: str, flow_id: int) -> str:
    output: list[str] = []
    for raw_line in str(value or "").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            output.append('<div class="message-space" aria-hidden="true"></div>')
            continue
        if stripped.startswith("![") and IMAGE_RE.fullmatch(stripped):
            image = IMAGE_RE.fullmatch(stripped)
            if image is None:
                raise ValueError("Markdown 图片标记解析失败")
            source = _safe_url(image.group(2), image=True)
            if source:
                output.append(
                    f'<img class="message-image" src="{html.escape(source, quote=True)}" '
                    f'alt="{html.escape(image.group(1), quote=True)}">'
                )
            continue
        depth = 0
        quote_text = raw_line.lstrip()
        while quote_text.startswith(">"):
            depth += 1
            quote_text = quote_text[1:].lstrip()
        body = _inline(quote_text if depth else raw_line, flow_id)
        if depth:
            output.append(
                f'<div class="message-quote depth-{min(depth, 3)}">{body}</div>'
            )
        elif stripped.startswith("**") and stripped.endswith("**"):
            output.append(f'<div class="message-header">{body}</div>')
        else:
            output.append(f'<div class="message-line">{body}</div>')
    return "".join(output) or '<div class="message-line"></div>'


def _inline(value: str, flow_id: int) -> str:
    result: list[str] = []
    cursor = 0
    pattern = re.compile(r"!\[[^\]]*\]\([^)]+\)|\[[^\]]+\]\([^)]+\)")
    for match in pattern.finditer(value):
        result.append(_format_text(value[cursor : match.start()]))
        token = match.group(0)
        image_match = IMAGE_RE.fullmatch(token)
        if image_match:
            source = _safe_url(image_match.group(2), image=True)
            if source:
                result.append(
                    f'<img class="inline-image" src="{html.escape(source, quote=True)}" '
                    f'alt="{html.escape(image_match.group(1), quote=True)}">'
                )
        else:
            link_match = LINK_RE.fullmatch(token)
            if link_match is None:
                raise ValueError("Markdown 链接标记解析失败")
            label = _format_text(link_match.group(1))
            target = link_match.group(2)
            if target.startswith("webcmd://"):
                action_id = target.removeprefix("webcmd://")
                result.append(
                    '<button type="button" class="inline-command" '
                    f'data-flow-id="{flow_id}" data-action-id="{html.escape(action_id, quote=True)}">'
                    f"{label}</button>"
                )
            elif safe_target := _safe_url(target):
                result.append(
                    f'<a href="{html.escape(safe_target, quote=True)}" target="_blank" '
                    f'rel="noopener noreferrer">{label}</a>'
                )
            else:
                result.append(label)
        cursor = match.end()
    result.append(_format_text(value[cursor:]))
    return "".join(result)


def _format_text(value: str) -> str:
    """正文一律按纯文本转义——消息通道已不再产生公式（2026-10）。"""

    return _format_plain_text(value)


def _format_plain_text(value: str) -> str:
    text = _unescape_markdown_punctuation(value)
    text = text.replace("&#91;", "[").replace("&#93;", "]")
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = escaped.replace("&amp;nbsp;", "&nbsp;")
    return escaped


def _plain(value: str) -> str:
    text = html.escape(str(value or ""), quote=False)
    return '<div class="message-line plain">' + text.replace("\n", "<br>") + "</div>"


def _unescape_markdown_punctuation(value: str) -> str:
    """显示 Markdown 转义字符本身代表的标点，不改动其他反斜杠。"""

    return re.sub(r"\\([\\`*{}\[\]()#+\-.!_>])", r"\1", str(value or ""))


def _safe_url(value: str, *, image: bool = False) -> str:
    text = html.unescape(str(value or "").strip())
    if text.startswith("/") and not text.startswith("//"):
        return text
    scheme = urlparse(text).scheme.lower()
    if scheme in {"http", "https"}:
        return text
    if image and scheme == "data" and text.startswith("data:image/"):
        return text
    return ""


__all__ = ["record_payload", "render_message_html"]
