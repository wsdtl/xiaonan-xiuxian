"""QQ 驱动器协议中立的派发运行时。

入站传输有两种：开放平台 webhook 与网关 WebSocket 长连接。两者收到的事件
类型、命令匹配、守卫和业务回调完全一致，只有字节到达的方式不同。所以命令
注册表、事件处理函数和事件队列只在这里维护一份，两个传输都从这里取用；
传输自己的握手、验签、排队策略仍留在各自模块。

共用模块级运行时必须引用计数：`.env` 允许同时启用两个传输，关闭时先关的
那一个不能把另一个还在使用的队列拆掉。
"""

from __future__ import annotations

from dataclasses import replace

from launch.config import config
from launch.log import C, logger

from ..context import (
    CONVERSATION_GROUP,
    CONVERSATION_PRIVATE,
    MessageContext,
    ReplyTarget,
)
from ..identity import resolve_group_id, resolve_user_id, route_fields
from ..request_scope import request_scope
from ..shared_dispatch import MessageDispatchMixin
from .event import QqMessageEvent, parse_message_event, rewrite_mentions_to_qq
from .manager import current_event, manager
from .rules import QqCommandMatch, QqCommandRegistry
from .runtime import QqDriverRuntime

# 两个传输共用的命令注册表与事件队列。
registry = QqCommandRegistry()
driver_runtime = QqDriverRuntime()

# 当前正在运行的传输数量；归零时才真正释放共享资源。
_running_transports = 0


def registry_log_parts() -> list[str]:
    """生成命令索引规模的启动日志片段，两个传输共用。"""

    return [
        C.kv("fullmatch", registry.fullmatch_count),
        C.kv("command", registry.command_count),
        C.kv("regex", registry.regex_rule_count),
    ]


async def start_dispatch_runtime(transport: str) -> None:
    """启动共享派发运行时；第二个传输只增加引用计数。"""

    global _running_transports
    _running_transports += 1
    if _running_transports > 1:
        logger.opt(colors=True).debug(
            C.join(
                C.ok("QQ 派发运行时已被其他传输启动"),
                C.kv("transport", transport),
                C.kv("refs", _running_transports),
            )
        )
        return

    registry.build_index()
    await manager.start()
    await driver_runtime.start(
        process_event=process_message_event,
        event_log_parts=event_log_parts,
    )


async def stop_dispatch_runtime(transport: str) -> None:
    """停止共享派发运行时；仅最后一个传输会真正释放资源。"""

    global _running_transports
    if _running_transports <= 0:
        return

    _running_transports -= 1
    if _running_transports > 0:
        logger.opt(colors=True).debug(
            C.join(
                C.ok("QQ 派发运行时仍被其他传输使用"),
                C.kv("transport", transport),
                C.kv("refs", _running_transports),
            )
        )
        return

    await driver_runtime.shutdown()
    await manager.shutdown()


async def submit_event(event: QqMessageEvent, *, transport: str, bot_key: str) -> None:
    """把一条已经解析的 QQ 事件送入共享队列。

    传输方式由驱动器显式传入，事件总线据此区分 webhook 与 websocket；
    后台队列仍负责单用户串行、全局并发上限和 event_id 去重。
    """

    event = replace(
        event,
        content=rewrite_mentions_to_qq(
            event.content,
            event.mention_ids,
            lambda openid: resolve_user_id(bot_key, openid),
        ),
        transport=transport,
        bot_key=bot_key,
    )
    await driver_runtime.enqueue_event(event, transport=transport, bot_key=bot_key)


def parse_gateway_event(
    payload: dict, event_type: str = ""
) -> QqMessageEvent | None:
    """把一条网关 op 0 payload 解析成规整事件。

    webhook 与 WebSocket 的 payload 结构完全一致，因此共用同一份解析器；
    这里额外做一次事件类型检查，让不关心的事件在入队前就被挡掉。
    """

    if not event_type:
        event_type, _data = _payload_event(payload)
    if event_type not in _SUPPORTED_EVENT_TYPES:
        return None
    return parse_message_event(payload, bot_name=bot_name())


def _payload_event(payload: dict) -> tuple[str, dict]:
    """从 payload 中读取事件类型与事件体，避免重复导入 ws 协议层。"""

    event_type = str(payload.get("t") or "").strip()
    data = payload.get("d")
    return event_type, data if isinstance(data, dict) else {}


_SUPPORTED_EVENT_TYPES = frozenset(
    {
        "C2C_MESSAGE_CREATE",
        "GROUP_AT_MESSAGE_CREATE",
        "GROUP_MESSAGE_AT_CREATE",
        "GROUP_MESSAGE_CREATE",
        "INTERACTION_CREATE",
    }
)


async def process_message_event(event: QqMessageEvent) -> bool:
    """在 QQ 当前事件上下文中匹配命令并执行回调。

    这是两个入站传输共用的唯一处理入口：命令匹配、block 执行计划、命令守卫
    和业务回调的参数注入都在这里完成，传输层不重复实现。
    """

    event_token = current_event.set(event)
    try:
        # 一条消息 = 一次请求：业务挂在这段范围里的资源（核心库连接复用）随消息收尾。
        with request_scope():
            matched = registry.match(event.content)
            if not matched:
                logger.opt(colors=True).debug(
                    C.join(C.warn("QQ 消息未命中命令"), *event_log_parts(event))
                )
                return False

            if not resolve_user_id(event.bot_key, event.user_id):
                logger.opt(colors=True).warning(
                    C.join(
                        C.warn("QQ 身份路由尚未建立"),
                        *event_log_parts(event, include_message=False),
                    )
                )
                await manager.send("身份同步中，请稍后再发一次")
                return True

            logger.opt(colors=True).success(
                C.join(
                    C.ok("QQ 命令命中"),
                    *event_log_parts(event),
                    C.kv("cmd", matched_commands_text(matched)),
                    C.kv("handlers", len(matched)),
                )
            )
            execution_plan = MessageDispatchMixin._execution_plan(matched)
            if await MessageDispatchMixin._guards_blocked(
                execution_plan,
                event,
                message_context=message_context,
                manager=manager,
            ):
                return True

            for item in execution_plan:
                await MessageDispatchMixin._call_rule(
                    item,
                    event,
                    message_context=message_context,
                    manager=manager,
                    raw_message=event.content,
                )
            return True
    finally:
        current_event.reset(event_token)


def message_context(item: QqCommandMatch, event: QqMessageEvent) -> MessageContext:
    """构造 QQ 驱动器自己的公共消息上下文。"""

    conversation_type = CONVERSATION_GROUP if event.is_group else CONVERSATION_PRIVATE
    route = route_fields(
        bot_key=event.bot_key,
        user_id=event.user_id,
        group_id=event.group_id,
    )
    reply_target = ReplyTarget(
        adapter="qq",
        user_id=event.user_id,
        target_id=event.group_id or event.user_id,
        conversation_type=conversation_type,
        driver_target=event,
    )
    return MessageContext(
        adapter="qq",
        user_id=route["route_user_id"] or event.user_id,
        request_id=event.event_id or event.interaction_id or event.message_id,
        command=item.command,
        message=item.message,
        raw_message=event.content,
        conversation_type=conversation_type,
        reply_target=reply_target,
        sender_name=event.sender_name,
        route_user_id=route["route_user_id"],
        route_group_id=route["route_group_id"],
    )


def event_log_parts(event: QqMessageEvent, include_message: bool = True) -> list[str]:
    """生成统一的事件日志摘要。"""

    display_user = resolve_user_id(event.bot_key, event.user_id) or "未绑定"
    display_group = (
        resolve_group_id(event.bot_key, event.group_id) or "未绑定"
        if event.group_id
        else "-"
    )
    parts = [
        C.kv("type", event_type_label(event.event_type)),
        C.kv("user", display_user),
        C.kv("group", display_group),
    ]
    if include_message:
        parts.append(C.kv("message", event.content))
    return parts


def event_type_label(event_type: str) -> str:
    """把 QQ 事件类型转成中文短标签。"""

    return {
        "C2C_MESSAGE_CREATE": "私聊",
        "GROUP_AT_MESSAGE_CREATE": "群艾特",
        "GROUP_MESSAGE_AT_CREATE": "群艾特",
        "GROUP_MESSAGE_CREATE": "群聊",
        "INTERACTION_CREATE": "按钮",
    }.get(event_type, event_type or "-")


def matched_commands_text(items: list[QqCommandMatch]) -> str:
    """压缩本次命中的命令片段，避免刷满日志。"""

    commands: list[str] = []
    seen: set[str] = set()
    for item in items:
        command = item.command or "-"
        if command in seen:
            continue
        seen.add(command)
        commands.append(command)
    if not commands:
        return "-"
    text = "、".join(commands[:3])
    if len(commands) > 3:
        text = f"{text} 等{len(commands)}个"
    return text


def bot_name() -> str:
    """读取配置里的机器人展示名。"""

    return config.get("QQ_BOT_NAME", "")


def payload_log_parts(payload: dict) -> list[str]:
    """生成 webhook payload 摘要。"""

    data = payload.get("d") if isinstance(payload.get("d"), dict) else {}
    return [
        C.kv("op", payload.get("op") or "-"),
        C.kv("type", payload.get("t") or "-"),
        C.kv("event", payload.get("id") or "-"),
        C.kv("msg", data.get("id") or "-"),
    ]


__all__ = [
    "bot_name",
    "driver_runtime",
    "event_log_parts",
    "event_type_label",
    "matched_commands_text",
    "message_context",
    "payload_log_parts",
    "parse_gateway_event",
    "process_message_event",
    "registry",
    "registry_log_parts",
    "start_dispatch_runtime",
    "stop_dispatch_runtime",
    "submit_event",
]
