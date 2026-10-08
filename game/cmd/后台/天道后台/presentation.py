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
        elif _is_formula_header(stripped) or (
            stripped.startswith("**") and stripped.endswith("**")
        ):
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
    return "".join(
        _formula_html(content, display=display)
        if formula
        else _format_plain_text(content)
        for formula, content, display in _formula_parts(value)
    )


def _format_plain_text(value: str) -> str:
    text = _unescape_markdown_punctuation(value)
    text = text.replace("&#91;", "[").replace("&#93;", "]")
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = escaped.replace("&amp;nbsp;", "&nbsp;")
    return escaped


def _formula_parts(value: str) -> list[tuple[bool, str, bool]]:
    """拆分受信任的公式边界；公式内容仍作为属性转义后交给 KaTeX。"""

    text = str(value or "")
    parts: list[tuple[bool, str, bool]] = []
    cursor = 0
    while cursor < len(text):
        start = _next_formula_start(text, cursor)
        if start < 0:
            parts.append((False, text[cursor:], False))
            break
        if start > cursor:
            parts.append((False, text[cursor:start], False))
        delimiter = "$$" if text.startswith("$$", start) else "$"
        end = _next_unescaped(text, delimiter, start + len(delimiter))
        if end < 0:
            parts.append((False, text[start:], False))
            break
        parts.append(
            (
                True,
                text[start + len(delimiter) : end],
                delimiter == "$$",
            )
        )
        cursor = end + len(delimiter)
    if not parts:
        parts.append((False, text, False))
    return parts


def _next_formula_start(value: str, start: int) -> int:
    index = start
    while index < len(value):
        index = value.find("$", index)
        if index < 0:
            return -1
        if not _is_escaped(value, index):
            return index
        index += 1
    return -1


def _next_unescaped(value: str, delimiter: str, start: int) -> int:
    index = start
    while index < len(value):
        index = value.find(delimiter, index)
        if index < 0:
            return -1
        if not _is_escaped(value, index):
            return index
        index += len(delimiter)
    return -1


def _is_escaped(value: str, index: int) -> bool:
    slashes = 0
    cursor = index - 1
    while cursor >= 0 and value[cursor] == "\\":
        slashes += 1
        cursor -= 1
    return slashes % 2 == 1


#: 公式里的命令：字母命令（text/textcolor/small/large…）与单字符命令（\; \, \ ）。
_FORMULA_COMMAND = re.compile(r"\\[A-Za-z]+|\\.")
_FORMULA_SPACES = frozenset({"\\ ", "\\;", "\\,", "\\quad", "\\qquad"})


def _formula_group(text: str, index: int) -> tuple[str, int]:
    """从 text[index] 是左花括号开始，取出配对的括号内容。"""

    if index >= len(text) or text[index] != "{":
        return "", index
    depth = 0
    cursor = index
    while cursor < len(text):
        if text[cursor] == "{":
            depth += 1
        elif text[cursor] == "}":
            depth -= 1
            if depth == 0:
                return text[index + 1 : cursor], cursor + 1
        cursor += 1
    return text[index + 1 :], len(text)


def _formula_plain(value: str) -> str:
    """把公式还原成玩家看得懂的短文本：只留 text 里的字，丢掉字号与颜色。"""

    text = str(value or "")
    out: list[str] = []
    cursor = 0
    while cursor < len(text):
        match = _FORMULA_COMMAND.match(text, cursor)
        if match:
            name = match.group(0)
            cursor = match.end()
            if cursor < len(text) and text[cursor] == "{":
                if name == "\\text":
                    content, cursor = _formula_group(text, cursor)
                    out.append(_formula_plain(content))
                elif name == "\\textcolor":
                    _, cursor = _formula_group(text, cursor)
                    if cursor < len(text) and text[cursor] == "{":
                        content, cursor = _formula_group(text, cursor)
                        out.append(_formula_plain(content))
                else:
                    content, cursor = _formula_group(text, cursor)
                    out.append(_formula_plain(content))
            elif name in _FORMULA_SPACES:
                out.append(" ")
            continue
        char = text[cursor]
        out.append(" " if char.isspace() else char)
        cursor += 1
    return " ".join("".join(out).split())


def _formula_html(value: str, *, display: bool) -> str:
    # data-plain 是给「KaTeX 没加载出来」时的降级：玩家该看到「空闲」，
    # 而不是 $\small{\textcolor{...}{\text{空闲}}}$ 这一串。
    return (
        '<span class="message-formula" data-latex="'
        + html.escape(value, quote=True)
        + '" data-plain="'
        + html.escape(_formula_plain(value), quote=True)
        + '" data-display="'
        + ("true" if display else "false")
        + '"></span>'
    )


def _is_formula_header(value: str) -> bool:
    return value.endswith("}$") and any(
        value.startswith(f"$\\{size}{{") for size in ("large", "Large")
    )


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
