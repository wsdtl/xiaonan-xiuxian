"""公共消息构造器。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import Any, Literal

from .schema import (
    Action,
    CommandLink,
    ContentLine,
    Document,
    DocumentBlock,
    DocumentMessage,
    FieldSeparator,
    HeaderBlock,
    ImageBlock,
    ImageMessage,
    InlineBlock,
    Link,
    NoteBlock,
    Progress,
    RichText,
    SectionBlock,
    Span,
    Status,
    Text,
)


def _rich(*parts: object) -> RichText:
    """把普通值和语义 span 整理为 RichText。"""

    result: list[Span] = []
    for part in parts:
        if isinstance(part, (Text, Status, Progress, Link, CommandLink, FieldSeparator)):
            result.append(part)
        elif isinstance(part, tuple) and all(
            isinstance(
                item,
                (Text, Status, Progress, Link, CommandLink, FieldSeparator),
            )
            for item in part
        ):
            result.extend(part)
        elif part is not None:
            text = str(part)
            _assert_semantic_text(text)
            result.append(Text(text))
    return tuple(result)


class DocumentBuilder:
    """按内容顺序构建不可变 DocumentMessage。"""

    def __init__(self) -> None:
        self._blocks: list[DocumentBlock] = []
        self._actions: list[Action] = []
        self._section_index: int | None = None

    def header(self, *parts: object) -> DocumentBuilder:
        """添加消息主标题。"""

        self._blocks.append(HeaderBlock(_rich(*parts)))
        self._section_index = None
        return self

    def inline_section(
        self,
        title: object,
        content: object = "",
        *,
        icon: str = "",
    ) -> DocumentBuilder:
        """添加标题与内容同一行的短信息。"""

        self._blocks.append(
            InlineBlock(_rich(title), _rich(content), str(icon or "").strip())
        )
        self._section_index = None
        return self

    def section(self, title: object, *, icon: str = "") -> DocumentBuilder:
        """开始一个新栏目；后续正文自动归属于该栏目。"""

        self._blocks.append(SectionBlock(_rich(title), (), str(icon or "").strip()))
        self._section_index = len(self._blocks) - 1
        return self

    def line(self, *parts: object) -> DocumentBuilder:
        """向当前栏目添加普通正文。"""

        self._append_section_line(ContentLine(_rich(*parts)))
        return self

    def small(self, *parts: object) -> DocumentBuilder:
        """添加整行统一小字说明。"""

        self._append_section_line(ContentLine(_rich(*parts), "caption"))
        return self

    def field(self, label: object, value: object) -> DocumentBuilder:
        """添加一个普通文本字段。"""

        return self.line(Text(f"{label}: "), value)

    def row(self, *items: tuple[object, object]) -> DocumentBuilder:
        """在同一行添加多个字段，分隔空白由渲染器决定。"""

        parts: list[Span] = []
        for index, (label, value) in enumerate(items):
            if index:
                parts.append(FieldSeparator())
            parts.extend((Text(f"{label}: "), *_rich(value)))
        self._append_section_line(ContentLine(tuple(parts)))
        return self

    def item(self, index: int, *parts: object) -> DocumentBuilder:
        """添加带稳定编号的列表项。"""

        if isinstance(index, bool) or not isinstance(index, int) or index < 1:
            raise ValueError("消息列表编号必须是正整数，不能使用内部业务标识")
        self._append_section_line(ContentLine(_rich(Text(f"[{index}] "), *parts)))
        return self

    def blank(self) -> DocumentBuilder:
        """在当前栏目正文内添加一行 Markdown 空引用。"""

        self._append_section_line(ContentLine(()))
        return self

    def note(self, *lines: object) -> DocumentBuilder:
        """添加正文之后、动作按钮之前的附加说明。"""

        content = tuple(ContentLine(parsed) for line in lines if (parsed := _rich(line)))
        if content:
            self._blocks.append(NoteBlock(content))
            self._section_index = None
        return self

    def image(
        self,
        url: object,
        *,
        alt: object = "图片",
        width: int | None = None,
        height: int | None = None,
    ) -> DocumentBuilder:
        """添加可与正文一起发送的公网图片。"""

        self._blocks.append(ImageBlock(str(url or ""), str(alt or ""), width, height))
        self._section_index = None
        return self

    def action(self, action: Action) -> DocumentBuilder:
        """添加一个交互动作。"""

        self._actions.append(action)
        return self

    def actions(self, actions: Iterable[Action]) -> DocumentBuilder:
        """按顺序批量添加交互动作。"""

        self._actions.extend(actions)
        return self

    def build(self) -> DocumentMessage:
        """校验交互不重复并冻结为不可变消息。"""

        ids = [action.action_id for action in self._actions]
        if len(ids) != len(set(ids)):
            raise ValueError("消息动作 action_id 不能重复")
        inline_commands = _inline_commands(self._blocks)
        bottom_commands = {action.data for action in self._actions}
        overlap = inline_commands & bottom_commands
        if overlap:
            raise ValueError(
                "正文联动不能与底部按钮重复：" + "、".join(sorted(overlap))
            )
        return DocumentMessage(Document(tuple(self._blocks), tuple(self._actions)))

    def _append_section_line(self, line: ContentLine) -> None:
        if self._section_index is None:
            raise ValueError("line/row/item 必须属于 section")
        block = self._blocks[self._section_index]
        if not isinstance(block, SectionBlock):
            raise TypeError("当前消息块不是 section")
        self._blocks[self._section_index] = replace(block, lines=block.lines + (line,))


def _assert_semantic_text(value: str) -> None:
    """公共协议拒绝业务手写 Markdown 结构符号。"""

    for line in value.splitlines() or [value]:
        stripped = line.lstrip()
        if stripped.startswith(">"):
            raise ValueError("公共消息文本不能手写 Markdown 引用前缀 >")
        if stripped == "---":
            raise ValueError("公共消息文本不能使用 Markdown 分割线 ---")


def _inline_commands(blocks: Iterable[DocumentBlock]) -> set[str]:
    """收集正文中的命令联动，避免同一命令同时占用两种交互层。"""

    commands: set[str] = set()
    for block in blocks:
        values: Iterable[RichText]
        if isinstance(block, HeaderBlock):
            values = (block.content,)
        elif isinstance(block, InlineBlock):
            values = (block.title, block.content)
        elif isinstance(block, SectionBlock):
            values = (block.title, *(line.content for line in block.lines))
        elif isinstance(block, NoteBlock):
            values = (line.content for line in block.lines)
        else:
            continue
        for value in values:
            for span in value:
                if isinstance(span, CommandLink):
                    commands.add(span.command)
    return commands


class M:
    """业务层唯一消息构造入口。"""

    @staticmethod
    def document() -> DocumentBuilder:
        return DocumentBuilder()

    @staticmethod
    def image(image: Any, caption: object = "") -> ImageMessage:
        return ImageMessage(image=image, caption=_rich(caption))

    @staticmethod
    def text(value: object, *, tone: str = "") -> RichText:
        return _rich(Text(str(value), tone))

    @staticmethod
    def status(value: object, *, tone: str = "info") -> Status:
        return Status(str(value), tone)

    @staticmethod
    def progress(
        value: float,
        maximum: float,
        *,
        tone: str = "info",
        display: Literal["none", "percent", "value", "both"] = "percent",
    ) -> Progress:
        return Progress(value, maximum, tone, display)

    @staticmethod
    def link(label: object, url: object) -> Link:
        return Link(_rich(label), str(url or "").strip())

    @staticmethod
    def command(
        label: object,
        command: object,
        *,
        submit: bool = True,
        reply: bool = False,
    ) -> CommandLink:
        return CommandLink(
            _rich(label), str(command or "").strip(), submit=submit, reply=reply
        )
