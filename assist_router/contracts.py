"""辅助路由的稳定事件与配对结果。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RouteEvent:
    """一条已归一化的入站消息；两个来源只差 source。"""

    source: str          # qq（官方）/ napcat
    bot_key: str
    scene: str           # private / group
    chat_id: str         # qq: group_openid 或 user_openid；NapCat: group_id 或 user_id
    sender_id: str       # qq: openid；NapCat: QQ 号
    sender_name: str
    message_id: str
    occurred_at: float
    text: str
    raw: dict


@dataclass(frozen=True)
class MatchResult:
    """一次配对的候选结果。"""

    qq_event: RouteEvent
    napcat_event: RouteEvent
    score: int
    reason: str
    identity_key: str
