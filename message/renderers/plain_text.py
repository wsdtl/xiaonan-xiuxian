"""公共 Document 到纯文本的明确降级渲染。"""

from __future__ import annotations

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


def render_plain_text(document: Document) -> str:
    lines: list[str] = []
    previous_block = None
    for block in document.blocks:
        if lines and _needs_block_separator(previous_block, block):
            lines.append("")
        if isinstance(block, HeaderBlock):
            lines.append(_render_rich(block.content))
        elif isinstance(block, InlineBlock):
            title = _title(block.title, block.icon)
            lines.append(f"{title}: {_render_rich(block.content)}".rstrip(": "))
        elif isinstance(block, SectionBlock):
            lines.append(_title(block.title, block.icon))
            lines.extend(_render_line(line) for line in block.lines)
        elif isinstance(block, ImageBlock):
            lines.append(f"[{block.alt}]")
        elif isinstance(block, NoteBlock):
            lines.extend(_render_line(line) for line in block.lines)
        previous_block = block
    return "\n".join(lines).strip()


def _needs_block_separator(previous: object, current: object) -> bool:
    return not (
        isinstance(previous, InlineBlock) and isinstance(current, InlineBlock)
    )


def render_rich_text(value: RichText) -> str:
    return _render_rich(value)


def _title(value: RichText, icon: str) -> str:
    return f"{icon_for(icon)} {_render_rich(value)}".strip()


def _render_line(value: ContentLine) -> str:
    return _render_rich(value.content)


def _render_rich(value: RichText) -> str:
    parts: list[str] = []
    for span in value:
        if isinstance(span, Text):
            parts.append(span.value.replace("\r", " ").replace("\n", " "))
        elif isinstance(span, Status):
            parts.append(span.value)
        elif isinstance(span, Progress):
            parts.append(span.label)
        elif isinstance(span, Link):
            parts.append(f"{_render_rich(span.label)} ({span.url})")
        elif isinstance(span, CommandLink):
            # 纯文本出口没有可点按钮：命令原文必须跟着标签一起出来，
            # 否则这份文本既点不了、也抄不出一条能执行的命令。
            parts.append(f"{_render_rich(span.label)}（{span.command}）")
        elif isinstance(span, FieldSeparator):
            parts.append(" | ")
    return "".join(parts)
