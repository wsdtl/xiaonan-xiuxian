"""公共 Document 到 Markdown 的结构渲染。"""

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
    CAPTION_SIZE_COMMAND,
    PROGRESS_EMPTY_COLOR,
    PROGRESS_EMPTY_GLYPH,
    PROGRESS_FILLED_COLOR,
    PROGRESS_FILLED_GLYPH,
    PROGRESS_SEGMENTS,
    LineSize,
    tone_style,
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
    """渲染一段 RichText，供协议驱动构造内联能力。"""

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
    # 只有明确的语义对象进入公式；普通 Markdown 文本保留原有层级和换行。
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
    parts: list[str] = []
    formula: list[str] = []
    semantic_line = force_formula or line_size == "caption"

    def flush_formula() -> None:
        if not formula:
            return
        parts.append(f"${_size(''.join(formula), line_size)}$")
        formula.clear()

    for span in value:
        if isinstance(span, Text):
            tone = span.tone or default_tone
            if semantic_line:
                formula.append(_text_expression(span.value, tone=tone))
            else:
                flush_formula()
                parts.append(_escape(span.value))
        elif isinstance(span, Status):
            style = tone_style(span.tone)
            if style.color:
                formula.append(_status_expression(span))
            else:
                flush_formula()
                parts.append(_escape(span.value))
        elif isinstance(span, Progress):
            formula.append(_progress_expression(span))
        elif isinstance(span, Link):
            flush_formula()
            parts.append(
                f"[{_render_rich(span.label, command_renderer, line_size=line_size, default_tone=default_tone, force_formula=_has_tone(span.label))}]({_escape_url(span.url)})"
            )
        elif isinstance(span, CommandLink):
            flush_formula()
            parts.append(
                command_renderer(span, line_size, default_tone, _has_tone(span.label))
                if command_renderer
                else _render_rich(
                    span.label,
                    None,
                    line_size=line_size,
                    default_tone=default_tone,
                    force_formula=_has_tone(span.label),
                )
            )
        elif isinstance(span, FieldSeparator):
            if semantic_line:
                formula.append(r"\text{ | }")
            else:
                flush_formula()
                parts.append("&nbsp;|&nbsp;")
    flush_formula()
    return "".join(parts)


def _has_tone(value: RichText) -> bool:
    """仅让明确的可点击名称保留局部公式装饰。"""

    return any(isinstance(span, Text) and bool(span.tone) for span in value)


def _render_header(block: HeaderBlock) -> str:
    text = "".join(span.value for span in block.content if isinstance(span, Text))
    # 标题只承担 Markdown 结构，不参与公式字号或颜色美化。
    return f"**{_escape(text)}**"


def _text_expression(value: str, *, tone: str) -> str:
    expression = f"\\text{{{_escape_latex(value)}}}"
    return _colorize(expression, tone_style(tone).color if tone else "")


def _status_expression(value: Status) -> str:
    style = tone_style(value.tone)
    return _colorize(f"\\text{{{_escape_latex(value.value)}}}", style.color)


def _progress_expression(value: Progress) -> str:
    style = tone_style(value.tone)
    filled = round(PROGRESS_SEGMENTS * value.ratio)
    empty = PROGRESS_SEGMENTS - filled
    parts: list[str] = []
    if filled:
        filled_text = f"\\text{{{PROGRESS_FILLED_GLYPH * filled}}}"
        parts.append(_colorize(filled_text, style.color or PROGRESS_FILLED_COLOR))
    if empty:
        parts.append(
            f"\\textcolor{{{PROGRESS_EMPTY_COLOR}}}"
            f"{{\\text{{{PROGRESS_EMPTY_GLYPH * empty}}}}}"
        )
    if value.label:
        label = f"\\text{{{_escape_latex(value.label)}}}"
        parts.append(f"\\;{_colorize(label, style.color or PROGRESS_FILLED_COLOR)}")
    return "".join(parts)


def _colorize(expression: str, color: str) -> str:
    """只在主题明确提供颜色时着色，否则保留原生公式文字。"""

    return f"\\textcolor{{{color}}}{{{expression}}}" if color else expression


def _size(value: str, line_size: LineSize) -> str:
    # QQ 公式基线比 Markdown 正文偏大；所有局部公式统一降一档。
    return f"\\{CAPTION_SIZE_COMMAND}{{{value}}}"


def _escape_latex(value: object) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "$": r"\$",
        "%": r"\%",
        "_": r"\_",
        "#": r"\#",
        "&": r"\&",
        "^": r"\^{}",
        "~": r"\~{}",
    }
    text = str(value).replace("\r", " ").replace("\n", " ")
    return "".join(replacements.get(character, character) for character in text)


def _escape(value: object) -> str:
    text = str(value or "")
    for token in ("\\", "`", "*", "_", "$"):
        text = text.replace(token, f"\\{token}")
    text = text.replace("[", "&#91;").replace("]", "&#93;")
    return text.replace("\r", " ").replace("\n", " ")


def _escape_url(value: object) -> str:
    return str(value or "").strip().replace(" ", "%20").replace(")", "%29")
