"""辅助路由：框架事件、用户别名、群别名的最小回归。"""

from __future__ import annotations

import asyncio
import time

from launch.message_events import emit_message_event, event_from_incoming
from assist_router.config import AssistRouterSettings
from assist_router.contracts import RouteEvent
from assist_router.matcher import match_group, match_user
from assist_router.service import AssistRouterService
from assist_router.store import AssistRouterStore


def test_store_creates_missing_database(tmp_path) -> None:
    path = tmp_path / "nested" / "router.db"
    store = AssistRouterStore(path)
    store.open()
    try:
        assert path.is_file()
    finally:
        store.close()


def test_message_event_carries_route_fields() -> None:
    now = time.time()
    event = event_from_incoming(
        adapter="qq",
        bot_key="app-1",
        transport="webhook",
        user_id="openid-1",
        request_id="request-1",
        group_id="group-1",
        message_id="message-1",
        occurred_at=now,
        content="路由字段",
        sender_name="邓晓楠",
    )
    assert event.bot_key == "app-1"
    assert event.transport == "webhook"
    assert event.group_id == "group-1"
    assert event.message_id == "message-1"
    assert event.occurred_at == now
    assert event.request_id == "request-1"


def test_qq_parser_carries_group_message_and_time() -> None:
    from launch.adapter.qq_protocol.event import parse_message_event

    event = parse_message_event(
        {
            "t": "GROUP_AT_MESSAGE_CREATE",
            "d": {
                "id": "message-1",
                "content": "<@bot> 关联测试",
                "group_openid": "group-openid-1",
                "timestamp": 1792963000,
                "author": {"user_openid": "openid-1", "username": "邓晓楠"},
            },
        },
        bot_name="晓楠",
    )
    assert event is not None
    assert event.group_id == "group-openid-1"
    assert event.message_id == "message-1"
    assert event.occurred_at == 1792963000.0
    assert event.sender_name == "邓晓楠"


def test_framework_bus_accepts_both_official_transports(tmp_path) -> None:
    async def run() -> None:
        service = AssistRouterService(
            AssistRouterSettings(db_path=tmp_path / "router.db", napcat_url="", napcat_token="")
        )
        service.start()
        try:
            for transport in ("webhook", "websocket"):
                emit_message_event(
                    event_from_incoming(
                        adapter="qq",
                        bot_key=f"bot-{transport}",
                        transport=transport,
                        user_id=f"openid-{transport}",
                        request_id=f"request-{transport}",
                        group_id="",
                        message_id=f"message-{transport}",
                        occurred_at=time.time(),
                        content=f"来源-{transport}",
                        sender_name="邓晓楠",
                    )
                )
            await asyncio.sleep(0.3)
            assert service.stats()["events"] == 2
        finally:
            await service.stop()

    asyncio.run(run())


def test_user_alias_is_global_across_bots(tmp_path) -> None:
    store = AssistRouterStore(tmp_path / "router.db")
    store.open()
    try:
        for bot, openid, message in (
            ("app-a", "openid-a", "第一个机器人消息"),
            ("app-b", "openid-b", "第二个机器人消息"),
        ):
            now = time.time()
            official = RouteEvent(
                "qq", bot, "private", openid, openid,
                "邓晓楠", f"q-{bot}", now, message, {},
            )
            napcat = RouteEvent(
                "napcat", "2466290035", "private", "1684193123", "1684193123",
                "邓晓楠", f"n-{bot}", now + 0.2, message, {},
            )
            official_id = store.insert_event(official)
            napcat_id = store.insert_event(napcat)
            result = match_user(
                official,
                official_id,
                store,
                window=3.0,
                confirm_score=80,
                auto_confirm=True,
            )
            assert result is not None
            store.mark_consumed("user", official_id, napcat_id)

        assert store.stats()["users"] == 1
        assert store.stats()["user_aliases"] == 2
        first = store.resolve_user(official_bot_key="app-a", openid="openid-a")
        second = store.resolve_user(official_bot_key="app-b", openid="openid-b")
        assert first is not None and first["qq_uin"] == "1684193123"
        assert second is not None and second["qq_uin"] == "1684193123"
    finally:
        store.close()


def test_group_alias_is_separate_from_user_alias(tmp_path) -> None:
    store = AssistRouterStore(tmp_path / "router.db")
    store.open()
    try:
        now = time.time()
        official = RouteEvent(
            "qq", "app-1", "group", "group-openid-1", "openid-1",
            "邓晓楠", "gq1", now, "群唯一消息", {},
        )
        napcat = RouteEvent(
            "napcat", "2466290035", "group", "123456", "1684193123",
            "邓晓楠", "gn1", now + 0.3, "群唯一消息", {},
        )
        official_id = store.insert_event(official)
        napcat_id = store.insert_event(napcat)
        result = match_group(
            official,
            official_id,
            store,
            window=3.0,
            confirm_score=80,
            auto_confirm=True,
        )
        assert result is not None
        assert store.stats()["groups"] == 1
        assert store.stats()["group_aliases"] == 1
        route = store.resolve_group(
            official_bot_key="app-1", group_openid="group-openid-1"
        )
        assert route is not None
        assert route["qq_group_id"] == "123456"
        assert store.stats()["user_aliases"] == 0
        store.mark_consumed("group", official_id, napcat_id)
    finally:
        store.close()


def test_group_message_can_seed_both_group_and_user_alias(tmp_path) -> None:
    store = AssistRouterStore(tmp_path / "router.db")
    store.open()
    try:
        now = time.time()
        official = RouteEvent(
            "qq", "app-1", "group", "group-openid-1", "openid-1",
            "邓晓楠", "gq2", now, "群用户双路由", {},
        )
        napcat = RouteEvent(
            "napcat", "2466290035", "group", "123456", "1684193123",
            "邓晓楠", "gn2", now + 0.2, "群用户双路由", {},
        )
        official_id = store.insert_event(official)
        napcat_id = store.insert_event(napcat)
        assert match_group(
            official, official_id, store,
            window=3.0, confirm_score=80, auto_confirm=True,
        ) is not None
        assert match_user(
            official, official_id, store,
            window=3.0, confirm_score=80, auto_confirm=True,
        ) is not None
        assert store.stats()["group_aliases"] == 1
        assert store.stats()["user_aliases"] == 1
        user = store.resolve_user(official_bot_key="app-1", openid="openid-1")
        assert user is not None and user["qq_uin"] == "1684193123"
        assert user["scene"] == "group"
        assert user["group_openid"] == "group-openid-1"
    finally:
        store.close()


def test_ambiguous_does_not_create_alias(tmp_path) -> None:
    store = AssistRouterStore(tmp_path / "router.db")
    store.open()
    try:
        now = time.time()
        for index in range(2):
            official = RouteEvent(
                "qq", "app-1", "private", f"openid-{index}", f"openid-{index}",
                "同名", f"q-{index}", now, "重复消息", {},
            )
            store.insert_event(official)
        napcat = RouteEvent(
            "napcat", "2466290035", "private", "1684193123", "1684193123",
            "同名", "n-1", now + 0.2, "重复消息", {},
        )
        napcat_id = store.insert_event(napcat)
        result = match_user(
            napcat,
            napcat_id,
            store,
            window=3.0,
            confirm_score=80,
            auto_confirm=True,
        )
        assert result is None
        assert store.stats()["user_aliases"] == 0
    finally:
        store.close()
