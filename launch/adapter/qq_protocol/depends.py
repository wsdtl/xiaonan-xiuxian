"""QQ 驱动器私有依赖。

公共回调参数只暴露跨驱动通用字段；业务确实需要 QQ 协议字段时，
通过本模块的 Depends 函数显式声明。
"""

from __future__ import annotations

from typing import Any

from ..context import current_message_context
from .event import QqMessageEvent
from .manager import current_event
from .target import QqSendTarget


def current_qq_event() -> QqMessageEvent:
    """读取当前 QQ 事件；非 QQ 上下文直接报错。"""

    context = current_message_context()
    if context is not None:
        if context.adapter != "qq":
            raise RuntimeError("当前消息不是 QQ 上下文")
        driver_target = context.reply_target.driver_target
        if isinstance(driver_target, QqMessageEvent):
            return driver_target
        raise RuntimeError("当前 QQ 上下文缺少事件")

    event = current_event.get()
    if isinstance(event, QqMessageEvent):
        return event
    raise RuntimeError("当前消息不是 QQ 上下文")


def current_qq_payload() -> dict[str, Any]:
    """读取 QQ webhook 原始 payload。"""

    return current_qq_event().raw


def current_qq_event_type() -> str:
    """读取当前 QQ 事件类型。"""

    return current_qq_event().event_type


def current_qq_event_id() -> str:
    """读取当前 QQ 事件 ID。"""

    return current_qq_event().event_id


def current_qq_message_id() -> str:
    """读取当前 QQ 消息 ID。"""

    return current_qq_event().message_id


def current_qq_user_id() -> str:
    """读取当前 QQ 用户编号，与公共 user_id 完全一致。"""

    return current_qq_event().user_id


def current_qq_group_id() -> str:
    """读取当前 QQ 群编号；私聊事件返回空字符串。"""

    return current_qq_event().group_id


def current_qq_interaction_id() -> str:
    """读取当前 QQ 按钮交互 ID；普通消息返回空字符串。"""

    return current_qq_event().interaction_id


def current_qq_send_target() -> QqSendTarget:
    """把当前 QQ 上下文转换成可发送目标。"""

    context = current_message_context()
    if context is not None:
        if context.adapter != "qq":
            raise RuntimeError("当前消息不是 QQ 上下文")
        driver_target = context.reply_target.driver_target
        if isinstance(driver_target, QqSendTarget):
            return driver_target
        if isinstance(driver_target, QqMessageEvent):
            return QqSendTarget.from_event(driver_target)

    return QqSendTarget.from_event(current_qq_event())
