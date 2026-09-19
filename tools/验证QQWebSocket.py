"""用本地回环假网关验证 QQ WebSocket 驱动器。

启动一个真的 WebSocket 服务端（回环地址），让真实驱动器按 `.env` 的
`QQ_WS_GATEWAY_URL` 连上去，然后逐项验证：

- 握手：校验 `Sec-WebSocket-Accept`，客户端帧必须掩码；
- 鉴权：op 2 Identify 携带正确 token/intents/shard，并能处理 READY；
- 心跳：按 Hello 周期收到 op 1，且首次 d 为 null；
- 事件：op 0 群消息经共享注册表命中命令，业务回调拿到正确参数；
- 回复：业务回复经 QQ 回复管理器落到 OpenAPI 请求载荷，并带被动消息锚点；
- 续连：op 7 之后下一次连接使用 op 6 Resume，并带上 session 与 seq；
- 致命码：4915 之后驱动器停止重连；
- 清理：shutdown 之后连接关闭、后台任务清空。

这里不访问真实 QQ 开放平台：OpenAPI 的 HTTP 层被就地替换，只记录载荷。
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

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _force_websocket_transport() -> None:
    """让本次进程按 websocket 入站注册命令。

    验证脚本必须自己决定跑哪条入站，不能依赖 `.env`：`MessageHandler` 在导入
    业务模块时只把回调注册到**当前启用**的驱动器上，默认入站是 webhook 时，
    本脚本注册的测试命令不会进 WebSocket 驱动器的命令表。

    用 `import_module` 而不是 `import launch.config`：`launch/__init__.py`
    导出了同名的 `config` 对象，后者拿到的是对象而不是模块。
    """

    config_module = importlib.import_module("launch.config")
    config_module.config.custom["QQ_TRANSPORT"] = "websocket"


_force_websocket_transport()

from launch.adapter.qq_protocol import client as client_module  # noqa: E402
from launch.adapter.qq_protocol.client import QqOpenApiClient  # noqa: E402
from launch.adapter.qq_protocol.manager import manager as qq_manager  # noqa: E402
from launch.adapter.qq_ws import QqWsEventHandler, gateway  # noqa: E402
from launch.adapter.qq_ws import handler as ws_handler_module  # noqa: E402
from launch.adapter import websocket as frames  # noqa: E402
from launch.log import logger  # noqa: E402

WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
TEST_COMMAND = "验证回环"
TEST_USER = "VERIFY-USER-OPENID"
TEST_GROUP = "VERIFY-GROUP-OPENID"
TEST_MESSAGE_ID = "VERIFY-MESSAGE-ID"
TEST_EVENT_ID = "VERIFY-EVENT-ID"
TEST_SESSION_ID = "VERIFY-SESSION-ID"
GATEWAY_HEARTBEAT_MS = 300


class Failure(RuntimeError):
    """假网关或断言发现的不一致。"""


@dataclass
class TestConfig:
    """驱动器测试模式：只连本地回环网关。"""

    data: dict[str, str] = field(
        default_factory=lambda: {
            "QQ_WS_INTENTS": "",
            "QQ_BOT_NAME": "验证机器人",
            "QQ_BOT_APP_ID": "1000000",
            "QQ_BOT_SECRET": "verify-secret",
        }
    )

    def get(self, name: str, default: str = "") -> str:
        return self.data.get(name, default)

    def get_list(self, name: str, default=()) -> list[str]:
        raw = self.get(name)
        return list(json.loads(raw)) if raw else list(default)


class RecordingClient(QqOpenApiClient):
    """把 OpenAPI 调用换成可观测的本地记录，不发起真实网络请求。"""

    def __init__(self) -> None:
        super().__init__(app_id="1000000", client_secret="verify-secret")
        self.api_calls: list[tuple[str, dict]] = []

    def _request_json(self, method, url, payload, headers):  # type: ignore[override]
        self.api_calls.append((f"{method} {url}", dict(payload)))
        if url.endswith("/getAppAccessToken"):
            return (
                200,
                json.dumps({"access_token": "verify-token", "expires_in": 7200}),
                {},
            )
        if str(url).endswith("/messages"):
            return 200, json.dumps({"id": "SENT-MESSAGE-ID"}), {}
        return 200, "{}", {}

    def sent_messages(self) -> list[dict]:
        """返回真正发给 QQ 的消息载荷。"""

        return [
            payload
            for target, payload in self.api_calls
            if str(target).endswith("/messages")
        ]

    def close(self) -> None:
        """测试客户端没有连接池需要释放。"""


class FakeGateway:
    """回环 WebSocket 服务端，模拟 QQ 网关的下行行为。"""

    def __init__(self) -> None:
        self.server: asyncio.AbstractServer | None = None
        self.port = 0
        self.connections = 0
        self.received: list[dict] = []
        self.masked_frames = 0
        self.unmasked_frames = 0
        self.now = 0
        self.last_seq_sent = 0
        self.failures: list[str] = []
        self._writer: asyncio.StreamWriter | None = None

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/websocket"

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

    def opcodes(self) -> list[int]:
        """返回客户端发来的全部 opcode 顺序。"""

        return [int(item.get("op", -1)) for item in self.received]

    def payloads(self, opcode: int) -> list[dict]:
        """返回指定 opcode 的完整 payload。"""

        return [item for item in self.received if int(item.get("op", -1)) == opcode]

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.connections += 1
        self._writer = writer
        self.now = 0
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
        except Failure as exc:
            # 断言在服务端协程里失败时不能吞掉，先记录再由主流程报告。
            self.failures.append(str(exc))
        finally:
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
        lines = raw.decode("latin-1").split("\r\n")
        if not lines[0].startswith("GET /websocket"):
            raise Failure(f"握手请求行不是 GET /websocket：{lines[0]!r}")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                name, _, value = line.partition(":")
                headers[name.strip().lower()] = value.strip()
        key = headers.get("sec-websocket-key", "")
        if not key:
            raise Failure("握手缺少 Sec-WebSocket-Key")
        if headers.get("sec-websocket-version") != "13":
            raise Failure("握手缺少 Sec-WebSocket-Version: 13")
        accept = base64.b64encode(
            hashlib.sha1(f"{key}{WEBSOCKET_GUID}".encode("ascii")).digest()
        ).decode("ascii")
        writer.write(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n"
                "\r\n"
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
                code, _reason = frames.decode_close(payload)
                # 回一个关闭帧再断开，让驱动器按关闭码决定重连策略。
                await self._close_with(code)
                return
            if opcode in (frames.OPCODE_PING, frames.OPCODE_PONG):
                continue

            message = json.loads(payload)
            self.received.append(message)
            await self._on_client_payload(message)

    async def _on_client_payload(self, message: dict) -> None:
        opcode = int(message.get("op", -1))

        if opcode == gateway.OP_IDENTIFY:
            data = message.get("d") or {}
            if data.get("token") != "QQBot verify-token":
                raise Failure(f"Identify token 不正确：{data.get('token')!r}")
            if int(data.get("intents", 0)) != gateway.resolve_intents():
                raise Failure(f"Identify intents 不正确：{data.get('intents')!r}")
            if data.get("shard") != [0, 1]:
                raise Failure(f"Identify shard 不正确：{data.get('shard')!r}")
            self.now = 1
            await self._send_json(
                {
                    "op": gateway.OP_DISPATCH,
                    "s": self.now,
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
            return

        if opcode == gateway.OP_RESUME:
            data = message.get("d") or {}
            if data.get("session_id") != TEST_SESSION_ID:
                raise Failure(f"Resume session_id 不正确：{data.get('session_id')!r}")
            if int(data.get("seq", -1)) != self.last_seq_sent:
                raise Failure(
                    f"Resume seq 不正确：{data.get('seq')!r}，"
                    f"假网关最后发出的是 {self.last_seq_sent}"
                )
            self.now = 2
            await self._send_json(
                {"op": gateway.OP_DISPATCH, "s": self.now, "t": "RESUMED", "d": ""}
            )
            return

        if opcode == gateway.OP_HEARTBEAT:
            if message.get("d") is not None:
                raise Failure(f"首次心跳 d 必须是 null：{message.get('d')!r}")
            await self._send_json({"op": gateway.OP_HEARTBEAT_ACK})
            return

    async def push_group_command(self, content: str) -> None:
        """向驱动器推送一条群 @ 机器人消息。"""

        self.now += 1
        await self._send_json(
            {
                "id": TEST_EVENT_ID,
                "op": gateway.OP_DISPATCH,
                "s": self.now,
                "t": "GROUP_AT_MESSAGE_CREATE",
                "d": {
                    "id": TEST_MESSAGE_ID,
                    "content": f"<@!BOT-SELF-ID> {content}",
                    "group_openid": TEST_GROUP,
                    "author": {"member_openid": TEST_USER, "username": "验证玩家"},
                    "mentions": [
                        {
                            "id": "BOT-SELF-ID",
                            "user_openid": "BOT-SELF-ID",
                            "is_you": True,
                        }
                    ],
                },
            }
        )

    async def push_reconnect(self) -> None:
        """发送 op 7，要求驱动器重连。"""

        await self._send_json({"op": gateway.OP_RECONNECT})

    async def _close_with(self, code: int) -> None:
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
        except (ConnectionResetError, BrokenPipeError, RuntimeError):
            return
        writer.close()

    async def _send_json(self, payload: dict) -> None:
        writer = self._writer
        if writer is None or writer.is_closing():
            return
        sequence = payload.get("s")
        if isinstance(sequence, int):
            self.last_seq_sent = sequence
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

        if masked:
            self.masked_frames += 1
        else:
            self.unmasked_frames += 1

        key = await reader.readexactly(4) if masked else b""
        payload = await reader.readexactly(length) if length else b""
        if masked:
            payload = frames.apply_mask(payload, key)
        return opcode, payload


async def wait_for(predicate, *, timeout: float = 5.0, interval: float = 0.02) -> bool:
    """轮询等待条件成立。"""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return bool(predicate())


async def run() -> list[str]:
    """执行全部验证项，返回失败清单。"""

    from launch.adapter import MessageHandler
    from launch.adapter.qq_protocol import manager as manager_module

    failures: list[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        if condition:
            print(f"  [通过] {label}")
            return
        text = f"{label}：{detail}" if detail else label
        failures.append(text)
        print(f"  [失败] {text}")

    received: list[tuple[str, str, str]] = []
    log_records: list[str] = []

    # 捕获 WARNING 及以上日志，让发送链路的失败原因直接出现在验证结果里。
    sink_id = logger.add(
        lambda message: log_records.append(str(message).strip()),
        level="WARNING",
        format="{message}",
    )

    @MessageHandler.command(TEST_COMMAND)
    async def verify_command(*, user_id: str, message: str, raw_message: str, **_) -> None:
        received.append((user_id, message, raw_message))
        await qq_manager.send(f"回环回复 {message}")

    config_patch = TestConfig()
    original_config = gateway.config
    recording = RecordingClient()

    # `client` 是按 `from .client import client` 绑进各个模块命名空间的，所以
    # 必须逐个模块替换；只改 client 模块的属性不会影响已经绑定的引用。
    patched_modules = (client_module, manager_module, ws_handler_module)
    original_clients = [(module, module.client) for module in patched_modules]

    gateway.config = config_patch
    for module in patched_modules:
        module.client = recording

    fake = FakeGateway()
    await fake.start()
    config_patch.data["QQ_WS_GATEWAY_URL"] = fake.url

    try:
        await QqWsEventHandler.run()
        check("驱动器已启动", QqWsEventHandler.runtime().running)

        check(
            "完成握手与鉴权",
            await wait_for(lambda: fake.connections >= 1 and 2 in fake.opcodes(), timeout=8),
            f"connections={fake.connections} opcodes={fake.opcodes()}",
        )
        check(
            "客户端发出的帧全部掩码",
            fake.unmasked_frames == 0 and fake.masked_frames > 0,
            f"掩码={fake.masked_frames} 未掩码={fake.unmasked_frames}",
        )
        identify = fake.payloads(gateway.OP_IDENTIFY)
        check("Identify 只发一次且 intents 正确", len(identify) == 1, f"identify={identify}")
        check(
            "鉴权后按 Hello 周期发送心跳",
            await wait_for(lambda: gateway.OP_HEARTBEAT in fake.opcodes(), timeout=3),
            f"opcodes={fake.opcodes()}",
        )

        await fake.push_group_command(f"{TEST_COMMAND} 参数甲")
        check(
            "群消息命中共享命令表并路由到业务回调",
            await wait_for(lambda: bool(received), timeout=5),
            f"received={received}",
        )
        if received:
            check("公共 user_id 来自 member_openid", received[0][0] == TEST_USER, received[0][0])
            check("command 参数解析正确", received[0][1] == "参数甲", received[0][1])
            check(
                "开头 @机器人 已被剥离",
                received[0][2].endswith(f"{TEST_COMMAND} 参数甲"),
                received[0][2],
            )

        check(
            "回复经 QQ 回复管理器发往 OpenAPI",
            await wait_for(lambda: bool(recording.sent_messages()), timeout=5),
            f"calls={[target for target, _ in recording.api_calls]} "
            f"warnings={log_records[-4:]}",
        )
        sent = recording.sent_messages()
        if sent:
            check(
                "回复载荷带被动消息锚点 msg_id",
                sent[0].get("msg_id") == TEST_MESSAGE_ID,
                str(sent[0]),
            )

        await fake.push_reconnect()
        check(
            "op 7 触发重连并改用 Resume",
            await wait_for(lambda: len(fake.payloads(gateway.OP_RESUME)) >= 1, timeout=8),
            f"opcodes={fake.opcodes()} connections={fake.connections}",
        )
        # 驱动器应当在连接断开时记住"s 为 2 的群消息已经处理过"，Resume 带上
        # 它，服务端才会补发这之后的事件；这里逐字段确认，不用宽松比较。
        expected_seq = 2
        resume = fake.payloads(gateway.OP_RESUME)
        if resume:
            data = resume[0].get("d") or {}
            check(
                "Resume 复用 session 与 seq",
                data.get("session_id") == TEST_SESSION_ID
                and data.get("seq") == expected_seq,
                str(resume[0]),
            )
        check(
            "重连后仍然心跳",
            await wait_for(
                lambda: len(fake.payloads(gateway.OP_HEARTBEAT)) >= 2, timeout=3
            ),
            f"heartbeats={len(fake.payloads(gateway.OP_HEARTBEAT))}",
        )

        check("假网关未记录到协议不一致", not fake.failures, "；".join(fake.failures))

        before = fake.connections
        await fake._close_with(4915)  # noqa: SLF001 - 假网关自己的关闭动作
        await asyncio.sleep(1.0)
        check(
            "4915 之后停止重连",
            fake.connections == before and not QqWsEventHandler.runtime().running,
            f"connections={fake.connections} running={QqWsEventHandler.runtime().running}",
        )

        await QqWsEventHandler.shutdown()
        check("shutdown 后没有残留连接任务", not QqWsEventHandler.runtime().running)
    finally:
        logger.remove(sink_id)
        gateway.config = original_config
        for module, original in original_clients:
            module.client = original
        await fake.stop()

    return failures


def main() -> int:
    """运行本地回环端到端验证。"""

    print("QQ WebSocket 驱动器回环验证")
    failures = asyncio.run(run())
    if failures:
        print(f"\n验证不成立 {len(failures)} 处：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\n全部通过：握手、鉴权、心跳、事件派发、回复、Resume、致命码与清理")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
