"""协议中立的消息上下文与发送意图。

业务层只能依赖本模块公开的用户、请求、会话和目标；QQ event 等协议对象
只可存在于 ReplyTarget.driver_target。
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

CONVERSATION_PRIVATE = "private"
CONVERSATION_GROUP = "group"

MENTION_DEFAULT = "default"
MENTION_NONE = "none"
MENTION_SENDER = "sender"


@dataclass(frozen=True)
class ReplyTarget:
    """一次回复的用户归属与实际发送目标。

    `user_id` 是游戏账号身份，`target_id` 是平台投递目标：私聊时通常相同，
    群聊时 `target_id` 是群号。`driver_target` 只给对应适配器保存协议对象，
    游戏层不读取它。
    """

    adapter: str
    user_id: str
    target_id: str
    conversation_type: str
    driver_target: Any = None

    def __post_init__(self) -> None:
        adapter = str(self.adapter or "").strip().lower()
        user_id = str(self.user_id or "").strip()
        target_id = str(self.target_id or "").strip()
        conversation_type = str(self.conversation_type or "").strip().lower()
        if not adapter:
            raise ValueError("ReplyTarget 缺少 adapter")
        if not target_id:
            raise ValueError("ReplyTarget 缺少 target_id")
        if conversation_type not in {CONVERSATION_PRIVATE, CONVERSATION_GROUP}:
            raise ValueError(f"ReplyTarget 会话类型无效：{self.conversation_type}")
        object.__setattr__(self, "adapter", adapter)
        object.__setattr__(self, "user_id", user_id)
        object.__setattr__(self, "target_id", target_id)
        object.__setattr__(self, "conversation_type", conversation_type)


@dataclass(frozen=True)
class MessageContext:
    """一条已规整消息的公共上下文。

    QQ payload、Local 事件等协议细节在进入这里前已经被适配器解释；命令
    回调只依赖这些稳定字段，因此同一组件可以由不同驱动器触发。
    """

    adapter: str
    user_id: str
    request_id: str
    command: str
    message: str
    raw_message: str
    conversation_type: str
    reply_target: ReplyTarget
    sender_name: str = ""

    def __post_init__(self) -> None:
        adapter = str(self.adapter or "").strip().lower()
        user_id = str(self.user_id or "").strip()
        request_id = str(self.request_id or "").strip()
        conversation_type = str(self.conversation_type or "").strip().lower()
        if not user_id:
            raise ValueError("MessageContext 缺少 user_id")
        if not request_id:
            raise ValueError("MessageContext 缺少 request_id")
        if self.reply_target.adapter != adapter:
            raise ValueError("MessageContext 与 ReplyTarget 的 adapter 不一致")
        if self.reply_target.conversation_type != conversation_type:
            raise ValueError("MessageContext 与 ReplyTarget 的会话类型不一致")
        if self.reply_target.user_id and self.reply_target.user_id != user_id:
            raise ValueError("MessageContext 与 ReplyTarget 的 user_id 不一致")
        object.__setattr__(self, "adapter", adapter)
        object.__setattr__(self, "user_id", user_id)
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "conversation_type", conversation_type)
        object.__setattr__(self, "sender_name", " ".join(str(self.sender_name or "").split()))


@dataclass(frozen=True)
class SendOptions:
    """业务层表达发送意图时保留的通用发送选项。

    选项只描述发送意图，不描述 QQ 或 Local 的载荷结构。驱动器是否支持
    某种展示形式，由驱动器自己的渲染器决定。
    """

    mention: str = MENTION_DEFAULT
    markdown: bool = True
    log: bool = True


@dataclass(frozen=True)
class SendRequest:
    """一次发送请求。

    `target` 为空时使用当前消息的回复目标；只有跨会话主动发送时才需要
    显式目标。`request_id` 用于日志和幂等关联，不由消息正文推断。
    """

    message: object
    target: ReplyTarget | None = None
    options: SendOptions = field(default_factory=SendOptions)
    request_id: object | None = None


_current_message_context: ContextVar[MessageContext | None] = ContextVar(
    "adapter_explicit_message_context",
    default=None,
)


def set_current_message_context(context: MessageContext) -> Token[MessageContext | None]:
    """设置当前消息上下文，并返回可 reset 的 token。"""

    return _current_message_context.set(context)


def reset_current_message_context(token: Token[MessageContext | None]) -> None:
    """恢复上一个消息上下文。"""

    _current_message_context.reset(token)


def current_message_context() -> MessageContext | None:
    """读取当前消息上下文。"""

    return _current_message_context.get()


def current_reply_target() -> ReplyTarget | None:
    """读取当前消息的默认回复目标。"""

    context = current_message_context()
    if context is None:
        return None
    return context.reply_target
