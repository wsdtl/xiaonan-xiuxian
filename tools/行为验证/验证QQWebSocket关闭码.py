"""验证 QQ WebSocket 驱动器关闭码决策与重连/续连路径。

主端到端验证在 `验证QQWebSocket.py`（握手、鉴权、心跳、派发、回复）。本文件
专门覆盖官方 WebSocket 错误码表要求的分支：

- 4009 / 4008 / 1000 / 1006：允许 Resume，下一次连接必须发 op 6；
- 4006 / 4007 / 4001 / 4002 / 4900：不允许 Resume，下一次连接必须重新 op 2；
- 4914 / 4915：机器人下架或封禁，直接停止重连；
- op 9 Invalid Session 的 d 决定还能不能 Resume；
- 每次重连后心跳任务都必须被回收，不能残留。

官方错误码语义见
https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/error-trace/websocket.html
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib
import json
import pathlib
import sys
from dataclasses import dataclass, field

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _force_websocket_transport() -> None:
    """让本次进程按 websocket 入站注册命令。

    验证脚本必须自己决定跑哪条入站，不能依赖 `.env`：`MessageHandler` 只把
    回调注册到**当前启用**的驱动器上，默认入站是 webhook 时本脚本注册的测试
    命令不会进 WebSocket 驱动器的命令表。

    用 `import_module` 而不是 `import launch.config`：`launch/__init__.py`
    导出了同名的 `config` 对象，后者拿到的是对象而不是模块。
    """

    config_module = importlib.import_module("launch.config")
    config_module.config.custom["QQ_TRANSPORT"] = "websocket"


_force_websocket_transport()

import launch.adapter.qq_protocol.client as client_module  # noqa: E402
import launch.adapter.qq_protocol.manager as manager_module  # noqa: E402
import launch.adapter.qq_ws.handler as ws_handler_module  # noqa: E402
from launch.adapter.qq_protocol.client import QqOpenApiClient  # noqa: E402
from launch.adapter.qq_ws import QqWsEventHandler, gateway  # noqa: E402
from launch.adapter import websocket as frames  # noqa: E402

WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
TEST_SESSION_ID = "MATRIX-SESSION-ID"
GATEWAY_HEARTBEAT_MS = 300

# 关闭码 → 下一次连接期望的 opcode（None 表示应当停止重连）。
#
# 期望值的依据是官方错误码表的"是否可以重试 RESUME"一列，而不是实现：
#   可以 Resume：4008 发 payload 过快、4009 连接过期，以及本地链路断开
#               1000/1006（会话未必失效，Resume 让服务端补发遗漏事件）；
#   不可 Resume：4001/4002 无效 opcode 或 payload、4006 无效 session、
#               4007 seq 错误、4900 内部错误 —— 必须丢弃会话重新 Identify；
#   不可连接：  4914 机器人已下架（只允许沙箱）、4915 已封禁 —— 停止重连。
EXPECTED_NEXT_OPCODE: dict[int, int | None] = {
    4009: gateway.OP_RESUME,
    4008: gateway.OP_RESUME,
    1000: gateway.OP_RESUME,
    1006: gateway.OP_RESUME,
    4006: gateway.OP_IDENTIFY,
    4007: gateway.OP_IDENTIFY,
    4001: gateway.OP_IDENTIFY,
    4002: gateway.OP_IDENTIFY,
    4900: gateway.OP_IDENTIFY,
    4914: None,
    4915: None,
}

# op 9 Invalid Session 的 d 表示服务端是否还允许 Resume（d=true 才行）。
EXPECTED_INVALID_SESSION: dict[bool, int] = {
    True: gateway.OP_RESUME,
    False: gateway.OP_IDENTIFY,
}

# 连接建立后的认证类 opcode；心跳不算一次连接尝试。
CONNECT_OPCODES = (gateway.OP_IDENTIFY, gateway.OP_RESUME)


@dataclass
class TestConfig:
    """驱动器测试模式：只连本地回环网关。"""

    data: dict[str, str] = field(default_factory=dict)

    def get(self, name: str, default: str = "") -> str:
        return self.data.get(name, default)

    def get_list(self, name: str, default=()) -> list[str]:
        raw = self.get(name)
        return list(json.loads(raw)) if raw else list(default)


class SilentClient(QqOpenApiClient):
    """隔离 OpenAPI：本文件不验证发送，只保证不会打到真实平台。"""

    def __init__(self) -> None:
        super().__init__(app_id="1000000", client_secret="verify-secret")

    def _request_json(self, method, url, payload, headers):  # type: ignore[override]
        if str(url).endswith("/getAppAccessToken"):
            return (
                200,
                json.dumps({"access_token": "verify-token", "expires_in": 7200}),
                {},
            )
        return 200, "{}", {}

    def close(self) -> None:
        """测试客户端没有连接池需要释放。"""


class MatrixGateway:
    """每个场景一个回环网关，可指定鉴权完成后以何种方式断开。"""

    def __init__(
        self,
        *,
        close_code: int | None = None,
        invalid_session: bool | None = None,
    ) -> None:
        self.close_code = close_code
        self.invalid_session = invalid_session
        self.server: asyncio.AbstractServer | None = None
        self.port = 0
        self.connections = 0
        self.authenticated = 0
        self.received: list[dict] = []
        self._writer: asyncio.StreamWriter | None = None
        self._writers: dict[int, asyncio.StreamWriter] = {}
        self._index = 0

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/websocket"

    def opcodes(self) -> list[int]:
        return [int(item.get("op", -1)) for item in self.received]

    def opcode_on_connection(self, index: int) -> int | None:
        """返回第 index 条连接（从 0 起）上的首个鉴权 opcode。"""

        for item in self.received:
            if item.get("connection_index") != index:
                continue
            opcode = int(item.get("op", -1))
            if opcode in CONNECT_OPCODES:
                return opcode
        return None

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        index = self.connections
        self.connections += 1
        self._index = index

        # 关闭旧连接的收尾协程可能比新连接晚执行；`self._writer` 只能被
        # 自己那条连接的收尾清空，否则会把新连接的发送通道一起抹掉。
        self._writers[index] = writer
        self._writer = writer
        try:
            await self._handshake(reader, writer)
            await self._send_json(
                {
                    "op": gateway.OP_HELLO,
                    "d": {"heartbeat_interval": GATEWAY_HEARTBEAT_MS},
                }
            )
            await self._serve(reader)
        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            return
        finally:
            self._writers.pop(index, None)
            if self._writers:
                self._writer = max(self._writers)
            else:
                self._writer = None
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionResetError, BrokenPipeError):
                return

    async def _handshake(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        raw = await reader.readuntil(b"\r\n\r\n")
        key = ""
        for line in raw.decode("latin-1").split("\r\n")[1:]:
            if ":" in line:
                name, _, value = line.partition(":")
                if name.strip().lower() == "sec-websocket-key":
                    key = value.strip()
        accept = base64.b64encode(
            hashlib.sha1(f"{key}{WEBSOCKET_GUID}".encode("ascii")).digest()
        ).decode("ascii")
        writer.write(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode("ascii")
        )
        await writer.drain()

    async def _serve(self, reader: asyncio.StreamReader) -> None:
        while True:
            frame = await self._read_frame(reader)
            if frame is None:
                return
            opcode, payload = frame
            if opcode == frames.OPCODE_CLOSE:
                return
            if opcode in (frames.OPCODE_PING, frames.OPCODE_PONG):
                continue

            message = json.loads(payload)
            message["connection_index"] = self._index
            self.received.append(message)
            await self._on_payload(message)

    async def _on_payload(self, message: dict) -> None:
        opcode = int(message.get("op", -1))

        if opcode == gateway.OP_IDENTIFY:
            await self._send_json(
                {
                    "op": gateway.OP_DISPATCH,
                    "s": 1,
                    "t": "READY",
                    "d": {
                        "version": 1,
                        "session_id": TEST_SESSION_ID,
                        "user": {
                            "id": "BOT-SELF-ID",
                            "username": "验证机器人",
                            "bot": True,
                        },
                        "shard": [0, 1],
                    },
                }
            )
            await self._after_auth()
            return

        if opcode == gateway.OP_RESUME:
            await self._send_json(
                {"op": gateway.OP_DISPATCH, "s": 2, "t": "RESUMED", "d": ""}
            )
            await self._after_auth()
            return

        if opcode == gateway.OP_HEARTBEAT:
            await self._send_json({"op": gateway.OP_HEARTBEAT_ACK})
            return

    async def _after_auth(self) -> None:
        """鉴权完成后按场景注入断开方式；每个场景只断第一次连接。"""

        if self._index > 0:
            return

        self.authenticated += 1

        if self.invalid_session is not None:
            await self._send_json(
                {"op": gateway.OP_INVALID_SESSION, "d": bool(self.invalid_session)}
            )
            await asyncio.sleep(0.05)
            await self._hard_close()
            print(f"    [网关] 连接{self._index} 注入 op9 d={self.invalid_session}")
            return

        if self.close_code is None:
            return

        if self.close_code == 1006:
            # 异常断开：不发关闭帧，直接断链路，客户端只能看到连接丢失。
            await self._hard_close()
            print(f"    [网关] 连接{self._index} 硬断开（模拟 1006）")
            return

        await self._send_close_frame(self.close_code)
        print(f"    [网关] 连接{self._index} 发送关闭帧 code={self.close_code}")

    async def _send_close_frame(self, code: int) -> None:
        writer = self._writer
        if writer is None or writer.is_closing():
            return
        try:
            writer.write(
                frames.encode_frame(
                    frames.OPCODE_CLOSE, frames.encode_close(code), mask=False
                )
            )
            await writer.drain()
            writer.close()
        except (ConnectionResetError, BrokenPipeError, RuntimeError):
            return

    async def _hard_close(self) -> None:
        writer = self._writer
        if writer is None:
            return
        try:
            transport = writer.transport
        except (RuntimeError, AttributeError):
            writer.close()
            return
        if transport is not None:
            transport.abort()

    async def _send_json(self, payload: dict) -> None:
        writer = self._writer
        if writer is None or writer.is_closing():
            return
        try:
            writer.write(
                frames.encode_frame(
                    frames.OPCODE_TEXT,
                    json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    mask=False,
                )
            )
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError, RuntimeError):
            return

    async def _read_frame(
        self, reader: asyncio.StreamReader
    ) -> tuple[int, bytes] | None:
        try:
            header = await reader.readexactly(2)
        except asyncio.IncompleteReadError:
            return None

        first, second = header[0], header[1]
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = int.from_bytes(await reader.readexactly(2), "big")
        elif length == 127:
            length = int.from_bytes(await reader.readexactly(8), "big")

        key = await reader.readexactly(4) if masked else b""
        payload = await reader.readexactly(length) if length else b""
        if masked:
            payload = frames.apply_mask(payload, key)
        return opcode, payload


async def wait_for(predicate, *, timeout: float = 10.0, interval: float = 0.02) -> bool:
    """轮询等待条件成立。"""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return bool(predicate())


def heartbeat_tasks() -> list[asyncio.Task]:
    """返回当前仍然存活的心跳任务。"""

    return [
        task
        for task in asyncio.all_tasks()
        if task.get_name().startswith("qq-ws-heartbeat") and not task.done()
    ]


async def run_scenario(
    *,
    close_code: int | None = None,
    invalid_session: bool | None = None,
    expected_next: int | None,
) -> tuple[list[str], MatrixGateway]:
    """跑一个断开场景，返回失败清单与该场景的网关。"""

    failures: list[str] = []
    fake = MatrixGateway(close_code=close_code, invalid_session=invalid_session)
    await fake.start()

    original_config = gateway.config
    gateway.config = TestConfig(
        data={
            "QQ_WS_GATEWAY_URL": fake.url,
            "QQ_WS_INTENTS": "",
            "QQ_BOT_NAME": "验证机器人",
        }
    )

    try:
        await QqWsEventHandler.run()

        if not await wait_for(lambda: fake.authenticated >= 1):
            failures.append(
                f"场景 {close_code or invalid_session}：第一次连接未完成鉴权"
                f"（connections={fake.connections} opcodes={fake.opcodes()}）"
            )
            return failures, fake

        if expected_next is None:
            stopped = await wait_for(
                lambda: not QqWsEventHandler.runtime().running, timeout=8
            )
            if not stopped:
                failures.append(
                    f"关闭码 {close_code}：应当停止重连，但仍在重连"
                    f"（connections={fake.connections}）"
                )
            return failures, fake

        if not await wait_for(lambda: fake.opcode_on_connection(1) is not None):
            failures.append(
                f"场景 {close_code or invalid_session}：没有等到第二次连接"
                f"（connections={fake.connections} opcodes={fake.opcodes()}）"
            )
            return failures, fake

        actual = fake.opcode_on_connection(1)
        if actual != expected_next:
            failures.append(
                f"场景 {close_code or invalid_session}："
                f"下一次应发 op {expected_next}，实际 op {actual}"
            )

        alive = heartbeat_tasks()
        if len(alive) > 1:
            failures.append(
                f"场景 {close_code or invalid_session}：残留 {len(alive)} 个心跳任务"
            )
        return failures, fake
    finally:
        await QqWsEventHandler.shutdown()
        gateway.config = original_config
        await fake.stop()


async def run() -> list[str]:
    """执行关闭码决策矩阵与 Invalid Session 分支。"""

    failures: list[str] = []

    for close_code, expected in EXPECTED_NEXT_OPCODE.items():
        scenario_failures, fake = await run_scenario(
            close_code=close_code, expected_next=expected
        )
        label = f"关闭码 {close_code} → " + (
            "停止重连" if expected is None else f"op {expected}"
        )
        if scenario_failures:
            failures.extend(scenario_failures)
            print(f"  [失败] {label}")
        else:
            print(f"  [通过] {label}（连接次数={fake.connections}）")

    for resumable, expected in EXPECTED_INVALID_SESSION.items():
        scenario_failures, fake = await run_scenario(
            invalid_session=resumable, expected_next=expected
        )
        label = f"op 9 d={resumable} → op {expected}"
        if scenario_failures:
            failures.extend(scenario_failures)
            print(f"  [失败] {label}")
        else:
            print(f"  [通过] {label}（连接次数={fake.connections}）")

    return failures


def main() -> int:
    """运行关闭码与续连决策验证。"""

    print("QQ WebSocket 关闭码 / 续连决策验证")

    recording = SilentClient()
    patched = (client_module, manager_module, ws_handler_module)
    originals = [(module, module.client) for module in patched]
    for module in patched:
        module.client = recording

    try:
        failures = asyncio.run(run())
    finally:
        for module, original in originals:
            module.client = original

    if failures:
        print(f"\n验证不成立 {len(failures)} 处：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\n全部通过：关闭码决策、Invalid Session 分支与重连后心跳回收")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
