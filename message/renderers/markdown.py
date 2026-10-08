"""公共 Document 到 Markdown 的结构渲染。

**这条通道不产生公式。** 2026-10 实测：QQ 客户端不渲染公式，`small` 包出来的源码会原样
露出（玩家看到的是「缺少目标」那一段前面挂着一串反斜杠命令）。所以状态、进度、带色调的
强调与小字在这里**一律纯文本**，只保留结构：图标、分级引用（标题一层、正文二层）、字段分隔、
链接与换行。

公式（KaTeX）只属于**后台网页**那条路，由服务端的 HTML 投影负责，那里的降级由
`tools/架构审查/检查公式降级.py` 守着（要求每个公式带非空 `data-plain`）。两条路互不替代。
"""

from __future__ import annotations

from collections.abc import Callable

from ..icons import icon_for
from ..schema import (
    CommandLink,
    ContentLine,
    Document,
    FieldSeparator,
    HeaderBlock,
    ImageBlock,
    InlineBlock,
    Link,
    NoteBlock,
    Progress,
    RichText,
    SectionBlock,
    Status,
    Text,
)
from ..theme import (
    PROGRESS_EMPTY_GLYPH,
    PROGRESS_FILLED_GLYPH,
    PROGRESS_SEGMENTS,
    LineSize,
)

CommandRenderer = Callable[[CommandLink, LineSize, str, bool], str]


def render_markdown(
    document: Document, *, command_renderer: CommandRenderer | None = None
) -> str:
    """按统一标题、正文和附加区边界渲染 Markdown。"""

    lines: list[str] = []
    previous_block = None
    for block in document.blocks:
        if isinstance(block, HeaderBlock):
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(_render_header(block))
            previous_block = block
            continue

        should_separate = isinstance(
            previous_block, (InlineBlock, SectionBlock, ImageBlock, NoteBlock)
        ) and not (
            isinstance(previous_block, InlineBlock) and isinstance(block, InlineBlock)
        )
        if should_separate and lines and lines[-1] != "> ":
            lines.append("> ")

        if isinstance(block, InlineBlock):
            title = _title(block.title, block.icon, command_renderer)
            content = _render_rich(block.content, command_renderer)
            lines.append(f"> {title}: {content}".rstrip())
        elif isinstance(block, SectionBlock):
            lines.append(
                f"> {_title(block.title, block.icon, command_renderer)}".rstrip()
            )
            for line in block.lines:
                value = _render_line(line, command_renderer)
                lines.append("> >" if not value else f"> > {value}")
        elif isinstance(block, ImageBlock):
            size = ""
            if block.width is not None:
                size += f" #{block.width}px"
            if block.height is not None:
                size += f" #{block.height}px"
            lines.append(f"![{_escape(block.alt)}{size}]({_escape_url(block.url)})")
        elif isinstance(block, NoteBlock):
            for line in block.lines:
                value = _render_line(line, command_renderer)
                lines.append(">" if not value else f"> {value}")
        previous_block = block

    return "\n".join(lines).strip()


def render_rich_markdown(
    value: RichText,
    *,
    command_renderer: CommandRenderer | None = None,
    line_size: LineSize = "body",
    default_tone: str = "",
    force_formula: bool = False,
) -> str:
    """渲染一段 RichText，供协议驱动构造内联能力。

    `line_size` / `default_tone` / `force_formula` 只为不动物协议驱动的调用方而保留：
    它们原来都服务于「谁进公式」，这条通道不再有公式，所以一律不再使用。
    """

    return _render_rich(
        value,
        command_renderer,
        line_size=line_size,
        default_tone=default_tone,
        force_formula=force_formula,
    )


def _title(value: RichText, icon: str, command_renderer: CommandRenderer | None) -> str:
    title = _render_rich(value, command_renderer)
    display_icon = icon_for(icon)
    return f"{display_icon} {title}".strip()


def _render_line(value: ContentLine, command_renderer: CommandRenderer | None) -> str:
    return _render_rich(
        value.content,
        command_renderer,
        line_size=value.size,
        default_tone="muted" if value.size == "caption" else "",
        force_formula=value.size == "caption",
    )


def _render_rich(
    value: RichText,
    command_renderer: CommandRenderer | None,
    *,
    line_size: LineSize = "body",
    default_tone: str = "",
    force_formula: bool = False,
) -> str:
    """一段富文本 → 正文。**不产生公式**：状态、进度、强调、小字都只是普通文字。"""

    del line_size, default_tone, force_formula
    parts: list[str] = []
    for span in value:
        if isinstance(span, Text):
            parts.append(_escape(span.value))
        elif isinstance(span, Status):
            parts.append(_escape(span.value))
        elif isinstance(span, Progress):
            parts.append(_progress_text(span))
        elif isinstance(span, Link):
            parts.append(f"[{_render_rich(span.label, None)}]({_escape_url(span.url)})")
        elif isinstance(span, CommandLink):
            parts.append(
                command_renderer(span, "body", "", False)
                if command_renderer
                else _render_rich(span.label, None)
            )
        elif isinstance(span, FieldSeparator):
            parts.append(" | ")
    return "".join(parts)


def _progress_text(value: Progress) -> str:
    """进度条用字形拼出来，纯文本即可——以前那段是公式，客户端不渲染就成了源码。"""

    filled = round(PROGRESS_SEGMENTS * value.ratio)
    empty = PROGRESS_SEGMENTS - filled
    bar = PROGRESS_FILLED_GLYPH * filled + PROGRESS_EMPTY_GLYPH * empty
    return f"{bar} {value.label}".rstrip() if value.label else bar


def _render_header(block: HeaderBlock) -> str:
    text = "".join(span.value for span in block.content if isinstance(span, Text))
    return f"**{_escape(text)}**"


def _escape(value: object) -> str:
    """转义 Markdown 标点：玩家名里的 \\ ` * _ $ 不能破坏消息结构。"""

    text = str(value or "")
    for token in ("\\", "`", "*", "_", "$"):
        text = text.replace(token, f"\\{token}")
    # 公开文本统一使用半角方括号。只有紧随圆括号的方括号才会组成
    # Markdown 链接；孤立的 [名称] 应原样交给客户端显示。
    return text.replace("\r", " ").replace("\n", " ")


def _escape_url(value: object) -> str:
    return str(value or "").strip().replace(" ", "%20").replace(")", "%29")


__all__ = ["render_markdown", "render_rich_markdown"]
