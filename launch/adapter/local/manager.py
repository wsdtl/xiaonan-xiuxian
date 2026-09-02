"""本地驱动器回复管理器。"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field

from launch.log import C, logger
from launch.message_events import emit_message_event, event_from_outgoing
from message import render_local_message

from ..context import SendOptions, SendRequest, current_reply_target
from .event import LocalCommandEvent

current_event: ContextVar[LocalCommandEvent | None] = ContextVar(
    "local_current_event",
    default=None,
)


@dataclass(frozen=True)
class LocalReply:
    """本地驱动器捕获到的一次业务回复。"""

    message: object
    user_id: str
    options: SendOptions
    request_id: object | None = None


@dataclass
class LocalDispatchResult:
    """本地驱动器分发结果。"""

    event: LocalCommandEvent
    matched: bool = False
    replies: list[LocalReply] = field(default_factory=list)
    matched_count: int = 0


_current_result: ContextVar[LocalDispatchResult | None] = ContextVar(
    "local_current_result",
    default=None,
)


class LocalReplyManager:
    """把业务回复收集到本地分发结果。"""

    async def shutdown(self) -> None:
        """本地驱动器没有外部连接；保留生命周期钩子以满足统一契约。"""

    def bind_result(self, result: LocalDispatchResult) -> Token[LocalDispatchResult | None]:
        """绑定当前分发结果，让 send(...) 可以记录回复。"""

        return _current_result.set(result)

    def reset_result(self, token: Token[LocalDispatchResult | None]) -> None:
        """恢复上一个本地分发结果。"""

        _current_result.reset(token)

    async def send(
        self,
        message: object,
        is_log: bool = True,
        request_id: object | None = None,
    ) -> bool:
        """记录一条本地回复。"""

        result = _current_result.get()
        if result is None:
            if is_log:
                logger.opt(colors=True).warning(
                    f"{C.warn('本地回复失败，缺少本地分发上下文')} {C.kv('user', '-') }"
                )
            return False

        request = self._normalize_request(message, is_log, request_id)
        if request.target is not None and request.target.adapter != "local":
            if request.options.log:
                logger.opt(colors=True).warning(
                    f"{C.warn('本地回复失败，目标驱动器不匹配')} {C.kv('adapter', request.target.adapter)}"
                )
            return False

        reply_user_id = self._reply_user_id(request, result.event.user_id)
        reply_request_id = request.request_id or result.event.event_id
        reply = LocalReply(
            message=render_local_message(request.message, markdown=request.options.markdown),
            user_id=reply_user_id,
            options=request.options,
            request_id=reply_request_id,
        )
        result.replies.append(reply)

        emit_message_event(
            event_from_outgoing(
                adapter="local",
                user_id=reply.user_id,
                request_id=reply_request_id,
                message=request.message,
            )
        )
        return True

    @staticmethod
    def _normalize_request(
        message: object,
        is_log: bool,
        request_id: object | None,
    ) -> SendRequest:
        """把普通 message 和显式 SendRequest 统一成发送请求。"""

        if isinstance(message, SendRequest):
            return message

        return SendRequest(
            message=message,
            target=current_reply_target(),
            options=SendOptions(log=is_log),
            request_id=request_id,
        )

    @staticmethod
    def _reply_user_id(request: SendRequest, fallback: str) -> str:
        """优先使用显式回复目标上的游戏用户身份。"""

        if request.target is not None and request.target.user_id:
            return str(request.target.user_id)
        event = current_event.get()
        if event is not None and event.user_id:
            return str(event.user_id)
        return str(fallback or "").strip()


manager = LocalReplyManager()
