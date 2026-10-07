"""验证 `QQ_TRANSPORT=both` 下两个 QQ 驱动器的引用计数生命周期。

`.env` 允许 webhook 与 WebSocket 同时启用。两者共用 `qq_protocol` 的模块级
运行时（命令表、事件队列、回复管理器），而 `lifespan` 是**逆序关停**的：

    启动：qq_wh.run()  →  qq_ws.run()
    关停：qq_ws.shutdown()  →  qq_wh.shutdown()

所以先关掉的那一个绝不能把另一个还在用的队列和发送线程池拆掉，否则关停顺序
一变，先关的那个驱动器会顺手弄死后关的那个——表现为关停阶段报错，或者运行中
的驱动器突然收不到回复。这个引用计数是共享运行时唯一的存在理由，因此单独验证。

本文件不访问真实平台：OpenAPI 的 HTTP 层被就地替换。
"""

from __future__ import annotations

import asyncio
import importlib
import json
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _force_both_transport() -> None:
    """本次进程必须同时启用两个 QQ 驱动器。

    不能依赖 `.env`：`MessageHandler` 只把回调注册到当前启用的驱动器上，
    这里要的正是"两个都启用"的状态。
    """

    config_module = importlib.import_module("launch.config")
    config_module.config.custom["QQ_TRANSPORT"] = "both"
    # WebSocket 侧只需要一个"启动了、可关停"的运行时；指向不可达的回环地址，
    # 让它安静退避重连，而不是去真实开放平台取网关地址。
    config_module.config.custom["QQ_WS_GATEWAY_URL"] = "ws://127.0.0.1:9/websocket"
    config_module.config.custom["QQ_WS_INTENTS"] = ""


_force_both_transport()

import launch.adapter.qq_protocol.client as client_module  # noqa: E402
import launch.adapter.qq_protocol.manager as manager_module  # noqa: E402
import launch.adapter.qq_wh.handler as wh_handler_module  # noqa: E402
import launch.adapter.qq_ws.handler as ws_handler_module  # noqa: E402
from launch.adapter import MessageHandler, registry  # noqa: E402
from launch.adapter.qq_protocol import processor  # noqa: E402
from launch.adapter.qq_protocol.client import QqOpenApiClient  # noqa: E402
from launch.adapter.qq_protocol.event import QqMessageEvent  # noqa: E402
from launch.adapter.qq_wh import QqEventHandler  # noqa: E402
from launch.adapter.qq_ws import QqWsEventHandler  # noqa: E402

TEST_COMMAND = "验证双驱"
TEST_USER = "BOTH-USER-OPENID"
TEST_GROUP = "BOTH-GROUP-OPENID"
TEST_MESSAGE_ID = "BOTH-MESSAGE-ID"
TEST_EVENT_ID = "BOTH-EVENT-ID"


class SilentClient(QqOpenApiClient):
    """隔离 OpenAPI：只记录载荷，不发起真实请求。"""

    def __init__(self) -> None:
        super().__init__(app_id="1000000", client_secret="verify-secret")
        self.sent: list[dict] = []

    def _request_json(self, method, url, payload, headers):  # type: ignore[override]
        if str(url).endswith("/getAppAccessToken"):
            return (
                200,
                json.dumps({"access_token": "verify-token", "expires_in": 7200}),
                {},
            )
        if str(url).endswith("/messages"):
            self.sent.append(dict(payload))
            return 200, json.dumps({"id": "SENT"}), {}
        return 200, "{}", {}

    def close(self) -> None:
        """测试客户端没有连接池需要释放。"""


def make_event() -> QqMessageEvent:
    """构造一条来自共享命令表的群消息事件。"""

    return QqMessageEvent(
        event_type="GROUP_AT_MESSAGE_CREATE",
        event_id=TEST_EVENT_ID,
        message_id=TEST_MESSAGE_ID,
        content=f"{TEST_COMMAND} 参数乙",
        user_id=TEST_USER,
        group_id=TEST_GROUP,
        raw={},
        sender_name="验证玩家",
    )


async def wait_for(predicate, *, timeout: float = 6.0, interval: float = 0.02) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return bool(predicate())


async def run() -> list[str]:
    failures: list[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        if condition:
            print(f"  [通过] {label}")
            return
        text = f"{label}：{detail}" if detail else label
        failures.append(text)
        print(f"  [失败] {text}")

    received: list[tuple[str, str]] = []

    @MessageHandler.command(TEST_COMMAND)
    async def verify_command(*, user_id: str, message: str, **_) -> None:
        received.append((user_id, message))
        from launch.adapter.qq_protocol.manager import manager as qq_manager

        await qq_manager.send(f"双驱回复 {message}")

    recording = SilentClient()
    patched = (
        client_module,
        manager_module,
        wh_handler_module,
        ws_handler_module,
    )
    originals = [(module, module.client) for module in patched]
    for module in patched:
        module.client = recording

    try:
        check(
            "both 模式同时启用两个 QQ 驱动器",
            registry.enabled_adapter_names() == ["qq", "qq_ws", "local"],
            str(registry.enabled_adapter_names()),
        )

        # 按 lifespan 的真实顺序启动：先 webhook，后 WebSocket。
        await QqEventHandler.run()
        await QqWsEventHandler.run()
        check("两个驱动器都已启动", processor._running_transports == 2, str(processor._running_transports))

        # 逆序关停：先关 WebSocket，此时 webhook 还在用共享运行时。
        await QqWsEventHandler.shutdown()
        check(
            "关掉 WebSocket 后共享运行时仍存活",
            processor._running_transports == 1,
            str(processor._running_transports),
        )

        handled = await processor.process_message_event(make_event())
        check("webhook 侧仍能派发命令", handled and bool(received), str(received))
        check(
            "webhook 侧仍能发出回复",
            await wait_for(lambda: bool(recording.sent)),
            f"sent={recording.sent}",
        )

        received.clear()
        await QqEventHandler.shutdown()
        check(
            "最后一个驱动器关停后引用归零",
            processor._running_transports == 0,
            str(processor._running_transports),
        )

        # 引用归零后共享运行时必须真的释放，而不是留下半个队列。
        check(
            "归零后回复队列已释放",
            manager_module.manager._send_queue is None,
            f"queue={manager_module.manager._send_queue!r}",
        )
        check(
            "归零后事件队列已释放",
            processor.driver_runtime._event_queue is None,
            f"queue={processor.driver_runtime._event_queue!r}",
        )

        # 反向顺序再验一次：先启动 WebSocket，再启动 webhook，先关 webhook。
        await QqWsEventHandler.run()
        await QqEventHandler.run()
        await QqEventHandler.shutdown()
        check(
            "反序关停同样不拆掉对方",
            processor._running_transports == 1,
            str(processor._running_transports),
        )

        received.clear()
        recording.sent.clear()
        handled = await processor.process_message_event(make_event())
        check(
            "反序下 WebSocket 侧仍能收发",
            handled
            and bool(received)
            and await wait_for(lambda: bool(recording.sent)),
            f"received={received} sent={recording.sent}",
        )

        await QqWsEventHandler.shutdown()
        check(
            "反序关停后引用归零",
            processor._running_transports == 0,
            str(processor._running_transports),
        )
    finally:
        for module, original in originals:
            module.client = original

    return failures


def main() -> int:
    """运行双驱动器引用计数生命周期验证。"""

    print("QQ_TRANSPORT=both 共享运行时引用计数验证")
    failures = asyncio.run(run())
    if failures:
        print(f"\n验证不成立 {len(failures)} 处：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\n全部通过：两种启停顺序下共享运行时都不会被提前拆掉")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
