"""框架身份端口与 MessageContext 的接线回归。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from launch.adapter.context import (
    CONVERSATION_GROUP,
    MessageContext,
    ReplyTarget,
)
from launch.adapter.identity import (
    clear_identity_resolver,
    register_identity_resolver,
    route_fields,
)
from launch.adapter.qq_protocol import processor
from launch.adapter.qq_protocol.event import (
    QqMessageEvent,
    normalize_content,
    rewrite_mentions_to_qq,
)
from launch.adapter.qq_protocol.processor import (
    driver_runtime,
    event_log_parts,
    message_context,
    submit_event,
)


def test_route_fields_use_registered_resolver() -> None:
    clear_identity_resolver()
    try:
        register_identity_resolver(
            user=lambda bot, openid: "1684193123" if openid == "openid-1" else "",
            group=lambda bot, group: "123456" if group == "group-openid-1" else "",
        )
        assert route_fields(bot_key="102134058", user_id="openid-1") == {
            "route_user_id": "1684193123",
            "route_group_id": "",
        }
        assert route_fields(
            bot_key="102134058",
            user_id="openid-1",
            group_id="group-openid-1",
        ) == {
            "route_user_id": "1684193123",
            "route_group_id": "123456",
        }
    finally:
        clear_identity_resolver()


def test_message_context_carries_route_ids() -> None:
    target = ReplyTarget(
        adapter="qq",
        user_id="openid-1",
        target_id="openid-1",
        conversation_type=CONVERSATION_GROUP,
    )
    context = MessageContext(
        adapter="qq",
        user_id="1684193123",
        request_id="request-1",
        command="角色",
        message="",
        raw_message="角色",
        conversation_type=CONVERSATION_GROUP,
        reply_target=target,
        route_user_id="1684193123",
        route_group_id="123456",
    )
    assert context.user_id == "1684193123"
    assert context.reply_target.user_id == "openid-1"
    assert context.route_user_id == "1684193123"
    assert context.route_group_id == "123456"


def test_qq_message_context_resolves_route() -> None:
    clear_identity_resolver()
    register_identity_resolver(
        user=lambda bot, openid: "1684193123" if openid == "openid-1" else "",
        group=lambda bot, group: "123456" if group == "group-openid-1" else "",
    )
    try:
        event = QqMessageEvent(
            event_type="GROUP_MESSAGE_CREATE",
            event_id="event-1",
            message_id="message-1",
            content="角色",
            user_id="openid-1",
            group_id="group-openid-1",
            occurred_at=1.0,
            raw={},
            sender_name="邓晓楠",
            bot_key="102134058",
            transport="webhook",
        )
        item = SimpleNamespace(command="角色", message="")
        context = message_context(item, event)
        assert context.user_id == "1684193123"
        assert context.route_user_id == "1684193123"
        assert context.route_group_id == "123456"
        assert context.reply_target.user_id == "openid-1"
    finally:
        clear_identity_resolver()


def test_mention_ids_can_be_rewritten_to_qq() -> None:
    content = normalize_content(
        "查看 <@openid-1>",
        event_type="GROUP_MESSAGE_CREATE",
        mentions=[{"user_openid": "openid-1"}],
    )
    assert content == "查看 openid-1"
    rewritten = rewrite_mentions_to_qq(
        content, ("openid-1",), lambda openid: "1684193123"
    )
    assert rewritten == "查看 1684193123"


def test_submit_event_rewrites_mention_before_queue(monkeypatch) -> None:
    clear_identity_resolver()
    register_identity_resolver(
        user=lambda bot, openid: "1684193123" if openid == "openid-1" else "",
    )
    captured: dict[str, object] = {}

    async def fake_enqueue(event, *, transport: str, bot_key: str) -> None:
        captured["event"] = event
        captured["transport"] = transport
        captured["bot_key"] = bot_key

    monkeypatch.setattr(driver_runtime, "enqueue_event", fake_enqueue)
    event = QqMessageEvent(
        event_type="GROUP_MESSAGE_CREATE",
        event_id="event-2",
        message_id="message-2",
        content="查看 openid-1",
        user_id="openid-1",
        group_id="group-openid-1",
        occurred_at=1.0,
        raw={},
        mention_ids=("openid-1",),
    )
    try:
        asyncio.run(
            submit_event(event, transport="websocket", bot_key="102134058")
        )
        queued = captured["event"]
        assert getattr(queued, "content") == "查看 1684193123"
        assert captured["transport"] == "websocket"
        assert captured["bot_key"] == "102134058"
    finally:
        clear_identity_resolver()


def test_qq_command_without_route_gets_sync_reply(monkeypatch) -> None:
    clear_identity_resolver()
    sent: list[str] = []

    async def fake_send(message, *args, **kwargs) -> bool:
        sent.append(str(message))
        return True

    monkeypatch.setattr(processor.registry, "match", lambda content: [object()])
    monkeypatch.setattr(processor.manager, "send", fake_send)
    event = QqMessageEvent(
        event_type="GROUP_MESSAGE_CREATE",
        event_id="event-3",
        message_id="message-3",
        content="角色",
        user_id="openid-without-route",
        group_id="group-openid-1",
        occurred_at=1.0,
        raw={},
        bot_key="102134058",
    )
    try:
        assert asyncio.run(processor.process_message_event(event)) is True
        assert sent == ["身份同步中，请稍后再发一次"]
    finally:
        clear_identity_resolver()


def test_event_log_shows_qq_user_not_openid() -> None:
    clear_identity_resolver()
    register_identity_resolver(
        user=lambda bot, openid: "1684193123" if openid == "openid-1" else "",
    )
    try:
        event = QqMessageEvent(
            event_type="GROUP_MESSAGE_CREATE",
            event_id="event-4",
            message_id="message-4",
            content="角色",
            user_id="openid-1",
            group_id="group-x",
            occurred_at=1.0,
            raw={},
            bot_key="102134058",
        )
        parts = event_log_parts(event, include_message=False)
        text = " ".join(parts)
        assert "1684193123" in text
        assert "openid-1" not in text
        assert "message-4" not in text
        assert "event-4" not in text
    finally:
        clear_identity_resolver()



