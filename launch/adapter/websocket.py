"""RFC6455 WebSocket 客户端。

这是框架级的协议原语，与 QQ 无关：任何需要长连接的驱动器都可以复用它。
实现范围严格限定在服务端推送 + 客户端回复所需的集合：

- 上游：`encode_frame` / `apply_mask` / `decode_close` 等帧编解码；
- `WebSocketConnection`：客户端 Upgrade 握手、收发、分片重组、Ping/Pong、
  关闭帧。

这里不理解任何业务 opcode 语义；QQ 网关的 opcode、intents 与重连策略在
`launch.adapter.qq_ws` 的 gateway 与 runtime 中。

刻意只用标准库 `asyncio` + `ssl`：本项目其余依赖都来自 `requirements.txt`，
为一条长连接再引入第三方 WebSocket 库并不划算。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import ssl
import struct
from asyncio import StreamReader, StreamWriter
from dataclasses import dataclass
from urllib.parse import urlsplit

from launch.log import C, logger

# ---------------------------------------------------------------- 帧编解码

OPCODE_CONTINUATION = 0x0
OPCODE_TEXT = 0x1
OPCODE_BINARY = 0x2
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA

CONTROL_OPCODES = frozenset({OPCODE_CLOSE, OPCODE_PING, OPCODE_PONG})

MAX_PAYLOAD_BYTES = 8 * 1024 * 1024


class WebSocketProtocolError(RuntimeError):
    """对端违反了 RFC6455，连接必须关闭。"""

    def __init__(self, message: str, *, close_code: int = 1002) -> None:
        self.close_code = int(close_code)
        super().__init__(message)


class WebSocketClosed(RuntimeError):
    """对端发送了关闭帧，或底层连接已经断开。"""

    def __init__(self, message: str, *, close_code: int = 1006) -> None:
        self.close_code = int(close_code)
        super().__init__(message)


def encode_frame(opcode: int, payload: bytes, *, mask: bool) -> bytes:
    """编码一帧。客户端方向必须传 `mask=True`。"""

    if opcode in CONTROL_OPCODES and len(payload) > 125:
        raise WebSocketProtocolError("控制帧载荷不能超过 125 字节")

    length = len(payload)
    header = bytearray()
    header.append(0x80 | opcode)

    mask_bit = 0x80 if mask else 0x00
    if length < 126:
        header.append(mask_bit | length)
    elif length < 65536:
        header.append(mask_bit | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(mask_bit | 127)
        header.extend(struct.pack("!Q", length))

    if not mask:
        return bytes(header) + payload

    key = os.urandom(4)
    return bytes(header) + key + apply_mask(payload, key)


def apply_mask(payload: bytes, key: bytes) -> bytes:
    """用 4 字节掩码处理载荷；同一函数可逆。"""

    if len(key) != 4:
        raise WebSocketProtocolError("WebSocket 掩码必须是 4 字节")

    result = bytearray(len(payload))
    for index, value in enumerate(payload):
        result[index] = value ^ key[index % 4]
    return bytes(result)


def encode_close(code: int = 1000, reason: str = "") -> bytes:
    """编码关闭帧载荷。"""

    text = str(reason or "").encode("utf-8")[:123]
    return struct.pack("!H", int(code)) + text if code else text


def decode_close(payload: bytes) -> tuple[int, str]:
    """解析关闭帧载荷；空载荷按 1005（无状态码）处理。"""

    if not payload:
        return 1005, ""
    if len(payload) < 2:
        raise WebSocketProtocolError("关闭帧载荷长度不合法")
    code = struct.unpack("!H", payload[:2])[0]
    return code, payload[2:].decode("utf-8", errors="replace")


# ------------------------------------------------------------------ 连接层

WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
HANDSHAKE_MAX_BYTES = 16 * 1024
HANDSHAKE_TIMEOUT_SECONDS = 15.0
DEFAULT_PORTS = {"ws": 80, "wss": 443}


@dataclass(frozen=True)
class WebSocketAddress:
    """握手与建连需要的地址信息。"""

    secure: bool
    host: str
    port: int
    resource: str

    @classmethod
    def parse(cls, url: str) -> "WebSocketAddress":
        """解析 ws/wss URL；非法 URL 直接报错。"""

        parts = urlsplit(str(url or "").strip())
        scheme = parts.scheme.lower()
        if scheme not in DEFAULT_PORTS:
            raise ValueError(f"WebSocket URL 只支持 ws/wss：{url}")
        host = parts.hostname or ""
        if not host:
            raise ValueError(f"WebSocket URL 缺少主机名：{url}")
        resource = parts.path or "/"
        if parts.query:
            resource = f"{resource}?{parts.query}"
        return cls(
            secure=scheme == "wss",
            host=host,
            port=parts.port or DEFAULT_PORTS[scheme],
            resource=resource,
        )

    @property
    def host_header(self) -> str:
        """生成 Host 头，默认端口不追加端口号。"""

        if self.port == DEFAULT_PORTS["wss" if self.secure else "ws"]:
            return self.host
        return f"{self.host}:{self.port}"


@dataclass(frozen=True)
class WebSocketFrame:
    """一帧的解析结果。"""

    opcode: int
    payload: bytes
    finished: bool


class WebSocketConnection:
    """一条已经完成握手的 WebSocket 连接。"""

    def __init__(self, reader: StreamReader, writer: StreamWriter) -> None:
        self._reader = reader
        self._writer = writer
        self._closed = False
        self.close_code = 0
        self.close_reason = ""

    @classmethod
    async def connect(
        cls,
        url: str,
        *,
        connect_timeout: float = HANDSHAKE_TIMEOUT_SECONDS,
    ) -> "WebSocketConnection":
        """建立 TCP/TLS 连接并完成 WebSocket 握手。"""

        address = WebSocketAddress.parse(url)
        ssl_context = ssl.create_default_context() if address.secure else None

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    address.host,
                    address.port,
                    ssl=ssl_context,
                    server_hostname=address.host if address.secure else None,
                ),
                timeout=connect_timeout,
            )
        except asyncio.TimeoutError as exc:
            raise WebSocketProtocolError(
                f"连接 WebSocket 超时：{address.host}:{address.port}"
            ) from exc

        connection = cls(reader, writer)
        try:
            await connection._handshake(address)
        except BaseException:
            await connection.close()
            raise
        return connection

    async def _handshake(self, address: WebSocketAddress) -> None:
        """发送 Upgrade 请求并校验服务端响应。"""

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {address.resource} HTTP/1.1\r\n"
            f"Host: {address.host_header}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self._writer.write(request.encode("ascii"))
        await self._writer.drain()

        try:
            raw = await asyncio.wait_for(
                self._reader.readuntil(b"\r\n\r\n"),
                timeout=HANDSHAKE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise WebSocketProtocolError("WebSocket 握手响应超时") from exc
        except asyncio.IncompleteReadError as exc:
            raise WebSocketClosed("WebSocket 握手期间连接被关闭") from exc

        if len(raw) > HANDSHAKE_MAX_BYTES:
            raise WebSocketProtocolError("WebSocket 握手响应过大")

        status_line, _, header_block = raw.decode("latin-1").partition("\r\n")
        headers = _parse_headers(header_block)
        if "101" not in status_line.split(" ")[:2]:
            raise WebSocketProtocolError(f"WebSocket 握手被拒绝：{status_line.strip()}")

        if str(headers.get("upgrade", "")).lower() != "websocket":
            raise WebSocketProtocolError("WebSocket 握手缺少 Upgrade: websocket")
        if "upgrade" not in str(headers.get("connection", "")).lower():
            raise WebSocketProtocolError("WebSocket 握手缺少 Connection: Upgrade")

        expected = base64.b64encode(
            hashlib.sha1(f"{key}{WEBSOCKET_GUID}".encode("ascii")).digest()
        ).decode("ascii")
        if str(headers.get("sec-websocket-accept", "")).strip() != expected:
            raise WebSocketProtocolError("WebSocket 握手 Sec-WebSocket-Accept 不匹配")

    async def send_text(self, text: str) -> None:
        """发送一个完整文本帧。"""

        await self._send_frame(OPCODE_TEXT, str(text).encode("utf-8"))

    async def send_close(self, code: int = 1000, reason: str = "") -> None:
        """发送关闭帧；重复调用只发送一次。"""

        if self._closed:
            return
        self._closed = True
        try:
            self._writer.write(
                encode_frame(OPCODE_CLOSE, encode_close(code, reason), mask=True)
            )
            await self._writer.drain()
        except (ConnectionError, OSError, RuntimeError):
            return

    async def receive(self) -> tuple[str, int | bytes]:
        """读取下一条完整数据消息。

        返回 `("text", str)` 或 `("binary", bytes)`。控制帧在这里处理完毕，
        不会返回给调用方。对端关闭或连接断开时抛出 `WebSocketClosed`，
        并带上关闭码供网关层决定是 Resume 还是 Identify。
        """

        buffer = bytearray()
        message_opcode = 0

        while True:
            frame = await self._read_frame()

            if frame.opcode in {OPCODE_PING, OPCODE_PONG}:
                if frame.opcode == OPCODE_PING:
                    await self._send_frame(OPCODE_PONG, frame.payload)
                continue

            if frame.opcode == OPCODE_CLOSE:
                code, reason = decode_close(frame.payload)
                await self.send_close(1000)
                await self.close()
                raise WebSocketClosed(
                    f"服务端关闭连接：{code} {reason}".strip(),
                    close_code=code or 1006,
                )

            if frame.opcode in {OPCODE_TEXT, OPCODE_BINARY}:
                if message_opcode:
                    raise WebSocketProtocolError("分片消息未结束就收到新的数据帧")
                message_opcode = frame.opcode
            elif frame.opcode == OPCODE_CONTINUATION:
                if not message_opcode:
                    raise WebSocketProtocolError("收到没有起始帧的续帧")
            else:
                raise WebSocketProtocolError(f"未知 opcode：{frame.opcode}")

            buffer.extend(frame.payload)
            if len(buffer) > MAX_PAYLOAD_BYTES:
                raise WebSocketProtocolError("WebSocket 消息超过长度上限")

            if not frame.finished:
                continue

            opcode = message_opcode
            payload = bytes(buffer)
            message_opcode = 0
            buffer.clear()

            if opcode == OPCODE_TEXT:
                return "text", payload.decode("utf-8", errors="replace")
            return "binary", payload

    async def _send_frame(self, opcode: int, payload: bytes) -> None:
        if self._closed and opcode != OPCODE_CLOSE:
            raise WebSocketClosed("WebSocket 连接已关闭")
        self._writer.write(encode_frame(opcode, payload, mask=True))
        await self._writer.drain()

    async def _read_frame(self) -> WebSocketFrame:
        """读取一帧，校验掩码方向并解掩码。"""

        try:
            header = await self._reader.readexactly(2)
        except asyncio.IncompleteReadError as exc:
            raise WebSocketClosed("WebSocket 连接已被对端断开") from exc

        first, second = header[0], header[1]
        finished = bool(first & 0x80)
        if first & 0x70:
            raise WebSocketProtocolError("WebSocket 帧保留了未协商的扩展位")
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F

        if length == 126:
            length = struct.unpack("!H", await self._readexactly(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", await self._readexactly(8))[0]
            if length & (1 << 63):
                raise WebSocketProtocolError("WebSocket 帧长度最高位必须为 0")

        if opcode in CONTROL_OPCODES and (not finished or length > 125):
            raise WebSocketProtocolError("控制帧必须完整且不超过 125 字节")
        if length > MAX_PAYLOAD_BYTES:
            raise WebSocketProtocolError("WebSocket 帧超过长度上限")
        if masked:
            raise WebSocketProtocolError("服务端帧不允许掩码")

        payload = await self._readexactly(length) if length else b""
        return WebSocketFrame(opcode=opcode, payload=payload, finished=finished)

    async def _readexactly(self, size: int) -> bytes:
        try:
            return await self._reader.readexactly(size)
        except asyncio.IncompleteReadError as exc:
            raise WebSocketClosed("WebSocket 连接已被对端断开") from exc

    async def close(self) -> None:
        """关闭底层连接；重复调用保持幂等。"""

        if self._writer.is_closing():
            return
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except (ConnectionError, OSError, ssl.SSLError):
            logger.opt(colors=True).debug(C.warn("WebSocket 关闭连接时出现网络错误"))


def _parse_headers(header_block: str) -> dict[str, str]:
    """把响应头解析成小写键的字典。"""

    headers: dict[str, str] = {}
    for line in header_block.split("\r\n"):
        if not line or ":" not in line:
            continue
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return headers


__all__ = [
    "CONTROL_OPCODES",
    "MAX_PAYLOAD_BYTES",
    "OPCODE_BINARY",
    "OPCODE_CLOSE",
    "OPCODE_CONTINUATION",
    "OPCODE_PING",
    "OPCODE_PONG",
    "OPCODE_TEXT",
    "WebSocketAddress",
    "WebSocketClosed",
    "WebSocketConnection",
    "WebSocketFrame",
    "WebSocketProtocolError",
    "apply_mask",
    "decode_close",
    "encode_close",
    "encode_frame",
]
