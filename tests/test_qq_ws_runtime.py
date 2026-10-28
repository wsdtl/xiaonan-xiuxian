"""QQ WebSocket 运行时的重连/鉴权回归。

这些用假连接与假网关信息，不访问真实 QQ：
- token 必须每次连接前现取，不能复用启动时的那一份；
- 鉴权被拒后要清 token、强刷网关并立即重试一次；
- 连续失败进入长冷却，不永久退出；
- 4914/4915 仍然停止。
"""

from __future__ import annotations

import asyncio
import importlib
import json
from typing import ClassVar

import pytest

from launch.adapter.websocket import WebSocketClosed

runtime_module = importlib.import_module("launch.adapter.qq_ws.runtime")


class FakeConnection:
    """按脚本回放的 WebSocket 连接。"""

    instances: ClassVar[list[FakeConnection]] = []

    def __init__(self, script: list[object]) -> None:
        self.script = list(script)
        self.sent: list[dict] = []
        self.closed = False

    @classmethod
    async def connect(cls, url: str, **kwargs: object) -> FakeConnection:
        if not cls.instances:
            raise AssertionError("没有预置的假连接")
        return cls.instances.pop(0)

    async def receive(self) -> tuple[str, str]:
        if not self.script:
            raise WebSocketClosed("假连接结束", close_code=1006)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return "text", json.dumps(item, ensure_ascii=False)

    async def send_text(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def close(self) -> None:
        self.closed = True


def hello() -> dict:
    return {"op": 10, "d": {"heartbeat_interval": 30000}}


def ready() -> dict:
    return {
        "op": 0,
        "s": 1,
        "t": "READY",
        "d": {"session_id": "session-1", "user": {"id": "bot-1"}},
    }


def resumed() -> dict:
    return {
        "op": 0,
        "s": 2,
        "t": "RESUMED",
        "d": {"session_id": "session-1"},
    }


def reconnect_request() -> dict:
    return {"op": 7, "d": None}


def invalid_session(resumable: bool = False) -> dict:
    return {"op": 9, "d": resumable}


def auth_payloads(connection: FakeConnection) -> list[dict]:
    return [payload for payload in connection.sent if payload.get("op") in (2, 6)]


def install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    connections: list[FakeConnection],
    *,
    gateway_info: dict | None = None,
) -> list[dict]:
    FakeConnection.instances = list(connections)
    monkeypatch.setattr(runtime_module, "WebSocketConnection", FakeConnection)
    monkeypatch.setattr(runtime_module.gateway, "gateway_url", lambda: "")

    calls: list[bool] = []

    async def fake_gateway_info(*, force: bool = False) -> dict:
        calls.append(force)
        return dict(
            gateway_info
            or {
                "url": "wss://fake.invalid",
                "shards": 1,
                "remaining": 10,
                "max_concurrency": 1,
            }
        )

    return calls


def test_reconnect_uses_fresh_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """op 7 后的重连必须重新取 token，而不是复用启动时那一份。"""

    first = FakeConnection([hello(), ready(), reconnect_request()])
    second = FakeConnection([hello(), resumed()])
    install_fakes(monkeypatch, [first, second])

    tokens = iter(("token-a", "token-b"))
    monkeypatch.setattr(runtime_module, "_access_token", lambda: next(tokens))

    async def scenario() -> None:
        runtime = runtime_module.QqGatewayRuntime(
            runtime_module.QqWsSettings(
                gateway_reconnect_delay_seconds=0.2,
                gateway_reconnect_jitter_seconds=0.0,
            )
        )
        sleeps: list[float] = []

        async def fake_info(*, force: bool = False) -> dict:
            return {
                "url": "wss://fake.invalid",
                "shards": 1,
                "remaining": 10,
                "max_concurrency": 1,
            }

        async def fake_sleep(delay: float, shard_id: int | None) -> None:
            sleeps.append(delay)

        original_receive = runtime._receive_loop

        async def stop_after_resume(
            connection: object, session: object, shard_id: int
        ) -> None:
            if connection is second:
                runtime._shutdown.set()
                return
            return await original_receive(connection, session, shard_id)

        monkeypatch.setattr(runtime, "_gateway_info", fake_info)
        monkeypatch.setattr(runtime, "_sleep_before_reconnect", fake_sleep)
        monkeypatch.setattr(runtime, "_receive_loop", stop_after_resume)

        await asyncio.wait_for(runtime._shard_loop(0, 1), timeout=5)

        assert [payload["d"]["token"] for payload in auth_payloads(first)] == [
            "QQBot token-a"
        ]
        second_auth = auth_payloads(second)
        assert [payload["d"]["token"] for payload in second_auth] == [
            "QQBot token-b"
        ]
        assert second_auth[0]["op"] == 6
        assert second_auth[0]["d"]["session_id"] == "session-1"
        assert second_auth[0]["d"]["seq"] == 1
        assert sleeps == [runtime.settings.gateway_reconnect_delay_seconds]

    asyncio.run(scenario())


def test_auth_rejection_refreshes_credentials_and_retries_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """op 9 非可恢复：清 token、强刷网关、立即用新 token 重试一次。"""

    first = FakeConnection([hello(), invalid_session(False)])
    second = FakeConnection([hello(), ready()])
    gateway_calls = install_fakes(monkeypatch, [first, second])

    tokens = iter(("token-a", "token-b"))
    monkeypatch.setattr(runtime_module, "_access_token", lambda: next(tokens))

    async def scenario() -> None:
        runtime = runtime_module.QqGatewayRuntime()
        cleared: list[bool] = []
        sleeps: list[float] = []

        async def fake_info(*, force: bool = False) -> dict:
            gateway_calls.append(force)
            return {
                "url": "wss://fake.invalid",
                "shards": 1,
                "remaining": 10,
                "max_concurrency": 1,
            }

        async def fake_sleep(delay: float, shard_id: int | None) -> None:
            sleeps.append(delay)

        async def stop_after_ready(
            connection: object, session: object, shard_id: int
        ) -> None:
            runtime._shutdown.set()

        monkeypatch.setattr(runtime, "_gateway_info", fake_info)
        monkeypatch.setattr(runtime_module, "_clear_access_token", lambda: cleared.append(True))
        monkeypatch.setattr(runtime, "_sleep_before_reconnect", fake_sleep)
        monkeypatch.setattr(runtime, "_receive_loop", stop_after_ready)

        await asyncio.wait_for(runtime._shard_loop(0, 1), timeout=5)

        assert cleared == [True]
        assert runtime.stats.auth_rejections == 1
        assert [payload["d"]["token"] for payload in auth_payloads(first)] == [
            "QQBot token-a"
        ]
        assert [payload["d"]["token"] for payload in auth_payloads(second)] == [
            "QQBot token-b"
        ]
        # 第一次被拒后立即重试，不先睡退避；第二次成功后直接停。
        assert sleeps == []

    asyncio.run(scenario())


def test_repeated_auth_failure_enters_long_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """连续被拒不能直接放弃，要进入长冷却后继续。"""

    first = FakeConnection([hello(), invalid_session(False)])
    second = FakeConnection([hello(), invalid_session(False)])
    install_fakes(monkeypatch, [first, second])

    tokens = iter(("token-a", "token-b"))
    monkeypatch.setattr(runtime_module, "_access_token", lambda: next(tokens))

    async def scenario() -> None:
        runtime = runtime_module.QqGatewayRuntime(
            runtime_module.QqWsSettings(
                max_closed_without_ready=2,
                auth_failure_cooldown_seconds=0.01,
                reconnect_interval_seconds=0.01,
            )
        )
        sleeps: list[float] = []

        async def fake_info(*, force: bool = False) -> dict:
            return {
                "url": "wss://fake.invalid",
                "shards": 1,
                "remaining": 10,
                "max_concurrency": 1,
            }

        async def fake_sleep(delay: float, shard_id: int | None) -> None:
            sleeps.append(delay)
            if delay == runtime.settings.auth_failure_cooldown_seconds:
                runtime._shutdown.set()

        monkeypatch.setattr(runtime, "_gateway_info", fake_info)
        monkeypatch.setattr(runtime_module, "_clear_access_token", lambda: None)
        monkeypatch.setattr(runtime, "_sleep_before_reconnect", fake_sleep)

        await asyncio.wait_for(runtime._shard_loop(0, 1), timeout=5)

        assert runtime.stats.auth_rejections == 2
        assert runtime.settings.auth_failure_cooldown_seconds in sleeps
        assert runtime._shutdown.is_set()

    asyncio.run(scenario())


def test_fatal_close_still_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    """4914/4915 仍然停止，不进入冷却重试。"""

    connection = FakeConnection(
        [hello(), WebSocketClosed("bot offline", close_code=4914)]
    )
    install_fakes(monkeypatch, [connection])

    async def scenario() -> None:
        runtime = runtime_module.QqGatewayRuntime()
        sleeps: list[float] = []
        monkeypatch.setattr(runtime_module, "_access_token", lambda: "token-a")

        async def fake_info(*, force: bool = False) -> dict:
            return {
                "url": "wss://fake.invalid",
                "shards": 1,
                "remaining": 10,
                "max_concurrency": 1,
            }

        async def fake_sleep(delay: float, shard_id: int | None) -> None:
            sleeps.append(delay)

        monkeypatch.setattr(runtime, "_gateway_info", fake_info)
        monkeypatch.setattr(runtime, "_sleep_before_reconnect", fake_sleep)

        await asyncio.wait_for(runtime._shard_loop(0, 1), timeout=5)

        assert runtime._shutdown.is_set()
        assert runtime.stats.last_close_code == 4914
        assert sleeps == []

    asyncio.run(scenario())


def test_gateway_info_has_no_token_and_is_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """网关信息只含地址/分片/额度；token 由连接前另行现取。"""

    calls: list[int] = []

    def fake_fetch() -> dict:
        calls.append(1)
        return {
            "url": "wss://fake.invalid",
            "shards": 1,
            "remaining": 10,
            "max_concurrency": 1,
        }

    monkeypatch.setattr(runtime_module.gateway, "gateway_url", lambda: "")
    monkeypatch.setattr(runtime_module, "_fetch_gateway_info", fake_fetch)

    async def scenario() -> None:
        runtime = runtime_module.QqGatewayRuntime()
        first = await runtime._gateway_info()
        second = await runtime._gateway_info()
        assert first is second
        assert "token" not in first
        assert len(calls) == 1

        await runtime._gateway_info(force=True)
        assert len(calls) == 2
        assert runtime.stats.gateway_refreshes == 2

    asyncio.run(scenario())


def test_connect_once_does_not_read_missing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """回归：网关信息没有 token 字段时，_connect_once 不能再 KeyError。"""

    async def scenario() -> None:
        runtime = runtime_module.QqGatewayRuntime()
        stopped = asyncio.Event()

        async def fake_info(*, force: bool = False) -> dict:
            return {
                "url": "wss://fake.invalid",
                "shards": 1,
                "remaining": 10,
                "max_concurrency": 1,
            }

        async def fake_shard(shard_id: int, shard_count: int) -> None:
            stopped.set()

        monkeypatch.setattr(runtime, "_gateway_info", fake_info)
        monkeypatch.setattr(runtime, "_shard_loop", fake_shard)

        await runtime._connect_once()
        await asyncio.wait_for(stopped.wait(), timeout=2)
        assert stopped.is_set()

    asyncio.run(scenario())


def test_gateway_info_exhausted_limit_is_not_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """remaining=0 时不能留下旧缓存，否则下一轮会拿它继续连。"""

    def fake_fetch() -> dict:
        return {
            "url": "wss://fake.invalid",
            "shards": 1,
            "remaining": 0,
            "max_concurrency": 1,
        }

    monkeypatch.setattr(runtime_module.gateway, "gateway_url", lambda: "")
    monkeypatch.setattr(runtime_module, "_fetch_gateway_info", fake_fetch)

    async def scenario() -> None:
        runtime = runtime_module.QqGatewayRuntime()
        with pytest.raises(RuntimeError, match="启动次数已用完"):
            await runtime._gateway_info()
        assert runtime._gateway_cache is None
        assert runtime.stats.gateway_refreshes == 0

    asyncio.run(scenario())


def test_start_runs_reconnect_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """从 start() 进入：首次鉴权、op 7、换 token 重连、Resume 都要走通。"""

    first = FakeConnection([hello(), ready(), reconnect_request()])
    second = FakeConnection([hello(), resumed()])
    install_fakes(monkeypatch, [first, second])

    tokens = iter(("token-a", "token-b"))
    monkeypatch.setattr(runtime_module, "_access_token", lambda: next(tokens))

    async def scenario() -> None:
        runtime = runtime_module.QqGatewayRuntime()
        original_receive = runtime._receive_loop

        async def fake_info(*, force: bool = False) -> dict:
            return {
                "url": "wss://fake.invalid",
                "shards": 1,
                "remaining": 10,
                "max_concurrency": 1,
            }

        async def fake_sleep(delay: float, shard_id: int | None) -> None:
            return

        async def stop_after_resume(
            connection: object, session: object, shard_id: int
        ) -> None:
            if connection is second:
                runtime._shutdown.set()
                return
            return await original_receive(connection, session, shard_id)

        monkeypatch.setattr(runtime, "_gateway_info", fake_info)
        monkeypatch.setattr(runtime, "_sleep_before_reconnect", fake_sleep)
        monkeypatch.setattr(runtime, "_receive_loop", stop_after_resume)

        await runtime.start(0)
        await asyncio.wait_for(runtime._shutdown.wait(), timeout=5)
        await runtime.shutdown()

        assert [payload["d"]["token"] for payload in auth_payloads(first)] == [
            "QQBot token-a"
        ]
        assert [payload["d"]["token"] for payload in auth_payloads(second)] == [
            "QQBot token-b"
        ]

    asyncio.run(scenario())


def test_invalid_session_in_receive_loop_refreshes_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """收包阶段收到 op 9 也要清 token、强刷网关并立即重试一次。"""

    first = FakeConnection([hello(), ready(), invalid_session(False)])
    second = FakeConnection([hello(), ready()])
    install_fakes(monkeypatch, [first, second])

    tokens = iter(("token-a", "token-b"))
    monkeypatch.setattr(runtime_module, "_access_token", lambda: next(tokens))

    async def scenario() -> None:
        runtime = runtime_module.QqGatewayRuntime()
        cleared: list[bool] = []
        sleeps: list[float] = []
        original_receive = runtime._receive_loop

        async def fake_info(*, force: bool = False) -> dict:
            return {
                "url": "wss://fake.invalid",
                "shards": 1,
                "remaining": 10,
                "max_concurrency": 1,
            }

        async def fake_sleep(delay: float, shard_id: int | None) -> None:
            sleeps.append(delay)

        async def stop_after_ready(
            connection: object, session: object, shard_id: int
        ) -> None:
            if connection is second:
                runtime._shutdown.set()
                return
            return await original_receive(connection, session, shard_id)

        monkeypatch.setattr(runtime, "_gateway_info", fake_info)
        monkeypatch.setattr(
            runtime_module, "_clear_access_token", lambda: cleared.append(True)
        )
        monkeypatch.setattr(runtime, "_sleep_before_reconnect", fake_sleep)
        monkeypatch.setattr(runtime, "_receive_loop", stop_after_ready)

        await asyncio.wait_for(runtime._shard_loop(0, 1), timeout=5)

        assert cleared == [True]
        assert runtime.stats.auth_rejections == 1
        assert [payload["d"]["token"] for payload in auth_payloads(first)] == [
            "QQBot token-a"
        ]
        assert [payload["d"]["token"] for payload in auth_payloads(second)] == [
            "QQBot token-b"
        ]
        assert sleeps == []

    asyncio.run(scenario())


def test_shutdown_1006_is_debug_not_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """主动关停时 1006 只记 debug；非关停的 1006 仍记 warning。"""

    class FakeLogger:
        def __init__(self) -> None:
            self.debugs: list[str] = []
            self.warnings: list[str] = []

        def opt(self, **kwargs: object) -> FakeLogger:
            return self

        def debug(self, message: object) -> None:
            self.debugs.append(str(message))

        def info(self, message: object) -> None:
            return

        def warning(self, message: object) -> None:
            self.warnings.append(str(message))

        def error(self, message: object) -> None:
            return

    fake_logger = FakeLogger()
    monkeypatch.setattr(runtime_module, "logger", fake_logger)

    async def scenario() -> None:
        runtime = runtime_module.QqGatewayRuntime()
        runtime._shutdown.set()
        runtime._handle_closed(
            WebSocketClosed("reload", close_code=1006),
            runtime_module.QqWsSession(session_id="s1", can_resume=True),
            0,
        )
        assert fake_logger.warnings == []
        assert fake_logger.debugs

        runtime = runtime_module.QqGatewayRuntime()
        runtime._handle_closed(
            WebSocketClosed("network", close_code=1006),
            runtime_module.QqWsSession(session_id="s1", can_resume=True),
            0,
        )
        assert fake_logger.warnings

    asyncio.run(scenario())


def test_gateway_reconnect_delay_has_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    """op 7 快速重连延迟在 [base, base+jitter] 内，不会退回 3 秒。"""

    monkeypatch.setattr(runtime_module.random, "uniform", lambda low, high: high)
    runtime = runtime_module.QqGatewayRuntime(
        runtime_module.QqWsSettings(
            gateway_reconnect_delay_seconds=0.2,
            gateway_reconnect_jitter_seconds=0.3,
        )
    )
    assert runtime._gateway_reconnect_delay() == pytest.approx(0.5)


def _install_adapter_config(monkeypatch: pytest.MonkeyPatch, adapter: object) -> None:
    """Config 是冻结 dataclass：整体替换，并同步 gateway 模块的本地引用。"""

    import importlib
    from dataclasses import replace

    from launch.adapter.qq_ws import gateway as gateway_module
    from launch.config import config as framework_config

    config_module = importlib.import_module("launch.config")
    updated = replace(framework_config, adapter=adapter)
    monkeypatch.setattr(config_module, "config", updated)
    monkeypatch.setattr(gateway_module, "config", updated)


def test_adapter_env_keys_are_read_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """.env 里的 QQ_TRANSPORT/QQ_WS_* 必须真的被读取。

    这些键被排除在 config.custom 之外；读取方必须走 Config.adapter，
    否则 .env 写 websocket 也会永远回落 webhook。
    """

    from launch.adapter.qq_ws import gateway as gateway_module
    from launch.adapter.registry import qq_transport
    from launch.config import AdapterConfig

    _install_adapter_config(
        monkeypatch,
        AdapterConfig(
            qq_transport="both",
            qq_ws_gateway_url="wss://override.invalid",
            qq_ws_intents='["GROUP_AND_C2C_EVENT", "INTERACTION"]',
        ),
    )

    assert qq_transport() == "both"
    assert gateway_module.gateway_url() == "wss://override.invalid"
    assert gateway_module.resolve_intents() == (1 << 25) | (1 << 26)


def test_adapter_intents_accepts_decimal(monkeypatch: pytest.MonkeyPatch) -> None:
    from launch.adapter.qq_ws import gateway as gateway_module
    from launch.config import AdapterConfig

    _install_adapter_config(monkeypatch, AdapterConfig("websocket", "", "123"))
    assert gateway_module.resolve_intents() == 123


def test_adapter_intents_rejects_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    from launch.adapter.qq_ws import gateway as gateway_module
    from launch.config import AdapterConfig

    _install_adapter_config(
        monkeypatch, AdapterConfig("websocket", "", "not-a-list")
    )
    with pytest.raises(ValueError, match="QQ_WS_INTENTS"):
        gateway_module.resolve_intents()
