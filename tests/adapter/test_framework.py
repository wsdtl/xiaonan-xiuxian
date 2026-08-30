from __future__ import annotations

import asyncio
from inspect import signature

import pytest

from launch.adapter import (
    AdapterCapabilities,
    CommandGuardContext,
    MessageContext,
    ReplyTarget,
    clear_command_guards,
    register_command_guard,
    run_command_guards,
)
from launch.adapter.depends import call_with_dependencies, current_context_value
from launch.adapter.local import LocalCommandEvent, LocalEventHandler
from launch.adapter.qq.event import parse_message_event
from launch.adapter.qq.rules import QqCommandRegistry
from launch.adapter.qq.target import QqSendTarget


def _run(awaitable):
    return asyncio.run(awaitable)


def _guard_context() -> CommandGuardContext:
    return CommandGuardContext(
        message_context=MessageContext(
            adapter="local",
            user_id="qq-1",
            request_id="event-1",
            command="测试",
            message="",
            raw_message="测试",
            conversation_type="private",
            reply_target=ReplyTarget("local", "qq-1", "qq-1", "private"),
            capabilities=AdapterCapabilities(),
        )
    )


def _invalid_guard(_):
    return None


def _broken_guard(_):
    raise RuntimeError("broken")


def test_dependency_context_is_isolated_and_reset_between_tasks() -> None:
    async def read_request_id(request_id: str) -> str:
        await asyncio.sleep(0)
        return current_context_value("request_id", "missing")

    async def run_concurrently() -> list[str]:
        return await asyncio.gather(
            call_with_dependencies(read_request_id, {"request_id": "request-a"}),
            call_with_dependencies(read_request_id, {"request_id": "request-b"}),
        )

    assert _run(run_concurrently()) == ["request-a", "request-b"]
    assert current_context_value("request_id") is None


def test_qq_events_normalize_protocol_identity_without_using_display_name() -> None:
    group = parse_message_event(
        {
            "t": "GROUP_AT_MESSAGE_CREATE",
            "id": "event-1",
            "d": {
                "id": "message-1",
                "content": "帮助",
                "group_openid": "group-1",
                "author": {
                    "member_openid": "qq-user-1",
                    "nickname": "群昵称",
                },
            },
        }
    )
    interaction = parse_message_event(
        {
            "t": "INTERACTION_CREATE",
            "id": "event-2",
            "d": {
                "id": "interaction-1",
                "group_openid": "group-1",
                "group_member_openid": "qq-user-1",
                "data": {"resolved": {"button_data": "帮助"}},
            },
        }
    )

    assert group is not None and interaction is not None
    assert (group.user_id, group.sender_name) == ("qq-user-1", "群昵称")
    assert QqSendTarget.from_event(group).group_id == "group-1"
    assert (interaction.user_id, interaction.group_id) == ("qq-user-1", "group-1")


def test_qq_event_strips_the_bots_display_mention_only() -> None:
    event = parse_message_event(
        {
            "t": "GROUP_MESSAGE_CREATE",
            "id": "event-mention",
            "d": {
                "id": "message-mention",
                "content": "@楠楠 人物",
                "group_openid": "group-1",
                "author": {"member_openid": "qq-user-1"},
                "mentions": [
                    {
                        "id": "bot-1",
                        "username": "楠楠",
                        "is_you": True,
                    }
                ],
            },
        },
        bot_name="楠楠",
    )

    assert event is not None
    assert event.content == "人物"


def test_qq_event_keeps_another_users_display_mention() -> None:
    event = parse_message_event(
        {
            "t": "GROUP_MESSAGE_CREATE",
            "id": "event-mention-other",
            "d": {
                "id": "message-mention-other",
                "content": "@顾听澜 赠送 赤阳花 1",
                "group_openid": "group-1",
                "author": {"member_openid": "qq-user-1"},
                "mentions": [
                    {
                        "id": "qq-user-2",
                        "username": "顾听澜",
                        "is_you": False,
                    }
                ],
            },
        }
    )

    assert event is not None
    assert event.content == "@顾听澜 赠送 赤阳花 1"


def test_message_context_rejects_mixed_user_ids() -> None:
    with pytest.raises(ValueError, match="user_id 不一致"):
        MessageContext(
            adapter="local",
            user_id="user-1",
            request_id="event-1",
            command="帮助",
            message="",
            raw_message="帮助",
            conversation_type="private",
            reply_target=ReplyTarget("local", "user-2", "user-2", "private"),
            capabilities=AdapterCapabilities(),
        )


def test_command_registration_requires_a_space_before_arguments() -> None:
    async def callback() -> None:
        return None

    registry = QqCommandRegistry()
    registry.register_command("去", callback, 100, True)

    matched = registry.match("去 天衡城")
    assert len(matched) == 1
    assert (matched[0].command, matched[0].message) == ("去", "天衡城")
    assert registry.match("去天衡城") == []
    assert LocalEventHandler._split_command("去 45 62") == ("去", "45 62")
    assert LocalEventHandler._split_command("去天衡城") == ("去天衡城", "")


@pytest.mark.parametrize(
    "guard",
    [_invalid_guard, _broken_guard],
)
def test_command_guards_fail_closed_and_cannot_be_bypassed(guard) -> None:
    clear_command_guards()
    register_command_guard("broken", guard)
    decision = _run(run_command_guards(_guard_context()))
    clear_command_guards()

    assert decision.blocked is True
    assert decision.reply is not None
    assert "bypass_guards" not in signature(LocalCommandEvent).parameters
    assert "bypass_guards" not in signature(LocalEventHandler.dispatch).parameters
