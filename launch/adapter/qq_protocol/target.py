"""QQ 主动发送目标。

业务层的公共 `ReplyTarget` 只描述 adapter/user_id/target_id/conversation_type。
QQ 真正发送需要 user_id、group_id、message_id 等目标字段；原始协议字段
只在 client.py 组装请求路径时出现。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..context import CONVERSATION_GROUP, CONVERSATION_PRIVATE, ReplyTarget
from .event import QqMessageEvent


@dataclass(frozen=True)
class QqSendTarget:
    """QQ OpenAPI 发送目标。

    message_id/event_id 为空时就是主动消息；从 QqMessageEvent 构造时会
    保留它们，用于普通被动回复。
    """

    conversation_type: str = CONVERSATION_PRIVATE
    user_id: str = ""
    group_id: str = ""
    message_id: str = ""
    event_id: str = ""
    is_wakeup: bool = False

    def __post_init__(self) -> None:
        conversation_type = str(self.conversation_type or "").strip().lower()
        if conversation_type not in {CONVERSATION_PRIVATE, CONVERSATION_GROUP}:
            raise ValueError(f"未知 QQ 会话类型：{self.conversation_type}")
        object.__setattr__(self, "conversation_type", conversation_type)
        object.__setattr__(self, "user_id", str(self.user_id or "").strip())
        object.__setattr__(self, "group_id", str(self.group_id or "").strip())
        object.__setattr__(self, "message_id", str(self.message_id or "").strip())
        object.__setattr__(self, "event_id", str(self.event_id or "").strip())
        if conversation_type == CONVERSATION_PRIVATE and not self.user_id:
            raise ValueError("QQ 私聊发送目标缺少 user_id")
        if conversation_type == CONVERSATION_GROUP and not self.group_id:
            raise ValueError("QQ 群聊发送目标缺少 group_id")

    @property
    def is_group(self) -> bool:
        """目标是否为群聊。"""

        return self.conversation_type == CONVERSATION_GROUP

    @property
    def is_private(self) -> bool:
        """目标是否为私聊。"""

        return self.conversation_type == CONVERSATION_PRIVATE

    @classmethod
    def from_event(cls, event: QqMessageEvent) -> QqSendTarget:
        """从入站事件构造带被动回复锚点的发送目标。"""

        return cls(
            conversation_type=CONVERSATION_GROUP if event.is_group else CONVERSATION_PRIVATE,
            user_id=event.user_id,
            group_id=event.group_id,
            message_id=event.message_id,
            event_id=event.event_id,
        )

    @classmethod
    def private(
        cls,
        user_id: str,
        *,
        is_wakeup: bool = False,
    ) -> QqSendTarget:
        """构造不依赖入站事件的私聊主动发送目标。"""

        user_id = str(user_id or "").strip()
        return cls(
            conversation_type=CONVERSATION_PRIVATE,
            user_id=user_id,
            is_wakeup=bool(is_wakeup),
        )

    @classmethod
    def group(
        cls,
        group_id: str,
        *,
        user_id: str = "",
    ) -> QqSendTarget:
        """构造不依赖入站事件的群聊主动发送目标。"""

        group_id = str(group_id or "").strip()
        user_id = str(user_id or "").strip()
        return cls(
            conversation_type=CONVERSATION_GROUP,
            user_id=user_id,
            group_id=group_id,
        )


def qq_private_target(
    user_id: str,
    *,
    is_wakeup: bool = False,
) -> ReplyTarget:
    """构造 QQ 私聊主动发送目标。"""

    target = QqSendTarget.private(
        user_id,
        is_wakeup=is_wakeup,
    )
    return ReplyTarget(
        adapter="qq",
        user_id=target.user_id,
        target_id=target.user_id,
        conversation_type=CONVERSATION_PRIVATE,
        driver_target=target,
    )


def qq_group_target(
    group_id: str,
    *,
    user_id: str = "",
) -> ReplyTarget:
    """构造 QQ 群聊主动发送目标。"""

    target = QqSendTarget.group(
        group_id,
        user_id=user_id,
    )
    return ReplyTarget(
        adapter="qq",
        user_id=target.user_id,
        target_id=target.group_id,
        conversation_type=CONVERSATION_GROUP,
        driver_target=target,
    )
