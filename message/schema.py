"""跨驱动消息语义对象。

这些对象只描述业务想表达的内容，不包含 Markdown 引号、QQ keyboard 或
OpenAPI 字段。驱动器必须把它们渲染成自己的输出协议。
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Literal, TypeAlias

from .theme import LineSize, normalize_line_size, normalize_tone


@dataclass(frozen=True)
class Text:
    """普通文本；tone 只表达语义，不接受颜色值。"""

    value: str
    tone: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", str(self.value))
        object.__setattr__(self, "tone", normalize_tone(self.tone))


@dataclass(frozen=True)
class Status:
    """使用统一语义色突出一个短状态。"""

    value: str
    tone: str = "info"

    def __post_init__(self) -> None:
        value = str(self.value or "").strip()
        if not value or any(character in value for character in "\r\n"):
            raise ValueError("消息状态必须是非空单行文本")
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "tone", normalize_tone(self.tone, default="info"))


@dataclass(frozen=True)
class Progress:
    """以固定宽度展示数值进度。"""

    value: float
    maximum: float
    tone: str = "info"
    display: Literal["none", "percent", "value", "both"] = "percent"

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or isinstance(self.maximum, bool):
            raise TypeError("消息进度不接受布尔值")
        try:
            value = float(self.value)
            maximum = float(self.maximum)
        except (TypeError, ValueError) as exc:
            raise TypeError("消息进度必须使用数值") from exc
        if not isfinite(value) or not isfinite(maximum):
            raise ValueError("消息进度必须使用有限数值")
        if maximum <= 0:
            raise ValueError("消息进度上限必须大于 0")
        if self.display not in {"none", "percent", "value", "both"}:
            raise ValueError(f"未知消息进度文字：{self.display}")
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "maximum", maximum)
        object.__setattr__(self, "tone", normalize_tone(self.tone, default="info"))

    @property
    def ratio(self) -> float:
        return min(1.0, max(0.0, self.value / self.maximum))

    @property
    def label(self) -> str:
        percent = f"{round(self.ratio * 100):d}%"
        value = f"{_number(self.value)} / {_number(self.maximum)}"
        return {
            "none": "",
            "percent": percent,
            "value": value,
            "both": f"{value} · {percent}",
        }[self.display]


@dataclass(frozen=True)
class Link:
    """带展示文本的普通网页链接。"""

    label: RichText
    url: str


@dataclass(frozen=True)
class CommandLink:
    """点击后向当前会话填入或发送命令的内联动作。"""

    label: RichText
    command: str
    submit: bool = True
    reply: bool = False


@dataclass(frozen=True)
class FieldSeparator:
    """字段组分隔符；具体空白由渲染器决定。"""


Span: TypeAlias = Text | Status | Progress | Link | CommandLink | FieldSeparator
RichText: TypeAlias = tuple[Span, ...]


@dataclass(frozen=True)
class ContentLine:
    """一整行正文；字号只能在行级统一指定。"""

    content: RichText
    size: LineSize = "body"

    def __post_init__(self) -> None:
        object.__setattr__(self, "size", normalize_line_size(self.size))


@dataclass(frozen=True)
class HeaderBlock:
    """消息顶部的主标题。"""

    content: RichText

    def __post_init__(self) -> None:
        if not self.content or any(not isinstance(span, Text) for span in self.content):
            raise ValueError("消息主标题只允许普通文本")
        if any(
            character in span.value for span in self.content for character in "\r\n"
        ):
            raise ValueError("消息主标题必须保持单行")


@dataclass(frozen=True)
class InlineBlock:
    """标题与内容位于同一行的短信息，例如通知和状态。"""

    title: RichText
    content: RichText
    icon: str = ""


@dataclass(frozen=True)
class SectionBlock:
    """带标题和归属正文的栏目。"""

    title: RichText
    lines: tuple[ContentLine, ...]
    icon: str = ""


@dataclass(frozen=True)
class ImageBlock:
    """文档中的公网图片；用于演出与正文保持在同一条消息。"""

    url: str
    alt: str = "图片"
    width: int | None = None
    height: int | None = None

    def __post_init__(self) -> None:
        url = str(self.url or "").strip()
        alt = str(self.alt or "").strip() or "图片"
        if not url or any(character in url for character in "\r\n"):
            raise ValueError("文档图片缺少有效 URL")
        if self.width is not None and self.width < 1:
            raise ValueError("文档图片宽度必须大于 0")
        if self.height is not None and self.height < 1:
            raise ValueError("文档图片高度必须大于 0")
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "alt", alt.replace("\r", " ").replace("\n", " "))


@dataclass(frozen=True)
class NoteBlock:
    """正文之后、按钮之前的附加说明区。"""

    lines: tuple[ContentLine, ...]


DocumentBlock: TypeAlias = (
    HeaderBlock | InlineBlock | SectionBlock | ImageBlock | NoteBlock
)


ActionBehavior = Literal["callback", "send", "fill", "link"]
ActionStyle = Literal["primary", "secondary"]
ActionPermission = Literal["everyone", "admins", "specified"]


@dataclass(frozen=True)
class Action:
    """跨协议交互意图，权限提示不能代替服务端鉴权。"""

    action_id: str
    label: str
    data: str
    behavior: ActionBehavior = "callback"
    style: ActionStyle = "primary"
    permission: ActionPermission = "everyone"
    specified_user_ids: tuple[str, ...] = ()
    reply: bool = False
    visited_label: str = ""

    def __post_init__(self) -> None:
        if not self.action_id.strip():
            raise ValueError("消息动作缺少稳定 action_id")
        if not self.label.strip():
            raise ValueError("消息动作缺少 label")
        if not self.data.strip():
            raise ValueError("消息动作缺少 data")
        if self.behavior == "callback" and self.data[-1].isspace():
            raise ValueError("callback 动作必须是完整命令，data 末尾不能保留参数空位")
        if self.behavior == "link" and self.reply:
            raise ValueError("链接动作不支持 reply")
        if self.permission == "specified" and not self.specified_user_ids:
            raise ValueError("specified 动作必须提供 specified_user_ids")


@dataclass(frozen=True)
class Document:
    """由有序内容块和交互动作组成的完整文档。"""

    blocks: tuple[DocumentBlock, ...] = ()
    actions: tuple[Action, ...] = ()


@dataclass(frozen=True)
class DocumentMessage:
    """可交给任意消息驱动器渲染的文档消息。"""

    document: Document


@dataclass(frozen=True)
class ImageMessage:
    """由图片数据和可选说明文字组成的图片消息。"""

    image: Any
    caption: RichText = ()


Message: TypeAlias = DocumentMessage | ImageMessage


@dataclass(frozen=True)
class RenderedMessage:
    """协议中立渲染结果，供本地驱动和调试工具读取。"""

    kind: Literal["markdown", "text", "image"]
    content: str = ""
    image: Any = None
    actions: tuple[Action, ...] = ()


def _number(value: float) -> str:
    if value.is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")
