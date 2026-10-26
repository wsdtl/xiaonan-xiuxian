"""天道后台的短期消息与登录会话模型。"""

from __future__ import annotations

from dataclasses import dataclass

from launch.message_events import MessageInteraction


@dataclass(frozen=True)
class ConsoleFlowRecord:
    """一条可以分页、实时推送和安全回放的消息记录。"""

    flow_id: int
    direction: str
    adapter: str
    request_id: str
    user_id: str
    sender_name: str
    message_type: str
    content: str
    image: str
    interactions: tuple[MessageInteraction, ...]
    content_truncated: bool
    created_at: str
    created_at_timestamp: float


@dataclass(frozen=True)
class ConsoleSession:
    """只保存在进程内的 Web 登录会话。"""

    session_id: str
    csrf_token: str
    username: str
    expires_at: float


__all__ = ["ConsoleFlowRecord", "ConsoleSession"]
