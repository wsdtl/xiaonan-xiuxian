"""存档读不出来时，守卫该放行什么、该挡什么。

真实事故：正式库的玩家状态一度是旧版中文键名，代码读不出来，于是**每条命令**都被挡，
连「帮助」也过不去——因为守卫先读一遍存档、再看规则，而那次读取只服务于「托管中」
这一条附加判断。这里把那个坑钉住：

- 「始终可用」的命令（帮助 / 查看 / 地图 / 装配台）：存档读不出来也**照常可用**；
- 需要看盘的命令（「已创建」这类）：仍然**失败即拒绝**，并给出「状态检查失败」。
"""

from __future__ import annotations

import asyncio

import pytest
from dataclasses import replace

import game.cmd.access_guard as access_guard
from launch.adapter import CommandGuardContext
from launch.adapter.context import (
    CONVERSATION_PRIVATE,
    MessageContext,
    ReplyTarget,
)


@pytest.fixture(scope="module")
def services(tmp_path_factory):
    import game.app as app

    original = app.game_config
    app.game_config = replace(
        original,
        database=replace(original.database, path=tmp_path_factory.mktemp("guard") / "game.db"),
    )
    try:
        value = app.build_game_services()
    finally:
        app.game_config = original
    yield value
    value.core.database.close()


def _context(metadata: dict) -> CommandGuardContext:
    target = ReplyTarget(
        adapter="local",
        user_id="P:守卫用例",
        target_id="P:守卫用例",
        conversation_type=CONVERSATION_PRIVATE,
    )
    message = MessageContext(
        adapter="local",
        user_id="P:守卫用例",
        request_id="守卫用例",
        command="",
        message="",
        raw_message="",
        conversation_type=CONVERSATION_PRIVATE,
        reply_target=target,
    )
    return CommandGuardContext(message_context=message, command_metadata=metadata)


def _break_state_read(services, monkeypatch):
    """让读存档这件事必然失败，复现真实事故：旧版中文键名让 DB 层抛 KeyError。"""

    async def boom(*_args, **_kwargs):
        raise KeyError("value")

    monkeypatch.setattr(services.core.database, "get", boom)
    monkeypatch.setattr(services.core.database, "get_many", boom)
    monkeypatch.setattr(access_guard, "current_game_services", lambda: services)


def test_always_available_command_survives_unreadable_state(services, monkeypatch):
    """存档读不出来，也不该把「始终可用」的命令挡掉。"""

    async def run():
        _break_state_read(services, monkeypatch)
        decision = await access_guard.game_access_guard(
            _context({"scope": "通用", "guard_rule": "始终可用"})
        )
        assert not decision.blocked, decision.reason

    asyncio.run(run())


def test_stateful_command_still_fails_closed(services, monkeypatch):
    """需要看盘的命令仍然失败即拒绝，并且理由是说得出的一句话。"""

    async def run():
        _break_state_read(services, monkeypatch)
        decision = await access_guard.game_access_guard(
            _context({"scope": "通用", "guard_rule": "已创建"})
        )
        assert decision.blocked
        assert decision.reason == "状态检查失败，请稍后重试"

    asyncio.run(run())


def test_missing_rule_name_is_named(services, monkeypatch):
    """元数据里没写守卫规则时，给的是「缺少规则」而不是「状态检查失败」。"""

    async def run():
        _break_state_read(services, monkeypatch)
        decision = await access_guard.game_access_guard(_context({"scope": "通用"}))
        assert decision.blocked
        assert "守卫规则" in decision.reason

    asyncio.run(run())
