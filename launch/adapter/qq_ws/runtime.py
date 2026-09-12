"""QQ 网关 WebSocket 连接运行时。

只负责"把网关上的字节变成 `QqMessageEvent` 并交给共用队列"这一段：
建连、Hello、Identify/Resume、心跳、分片、重连退避和关闭清理。

命令匹配、守卫、业务回调与回复发送全部复用 `launch.adapter.qq_protocol`，
本文件不重复实现；底层帧与连接由框架级 `launch.adapter.websocket` 提供。
官方连接维护语义见
https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/event-emit.html
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from launch.log import C, logger

from ..qq_protocol import processor
from ..qq_protocol.event import QqMessageEvent
from ..websocket import WebSocketClosed, WebSocketConnection, WebSocketProtocolError
from . import gateway


@dataclass(frozen=True)
class QqWsSettings:
    """WebSocket 传输自己的连接参数。

    重连退避从 3 秒起步翻倍到 60 秒封顶：QQ 网关在维护或封禁时不应该被
    本机以固定频率猛敲，但正常抖动又要能快速恢复。
    """

    reconnect_interval_seconds: float = 3.0
    max_reconnect_interval_seconds: float = 60.0
    identify_timeout_seconds: float = 15.0
    connect_timeout_seconds: float = 15.0
    shutdown_grace_seconds: float = 3.0
    max_closed_without_ready: int = 8


@dataclass
class QqWsSession:
    """一条连接上的会话状态。

    `session_id`/`seq` 是 Resume 的全部依据；`can_resume` 为假时必须重新
    Identify，不能带着过期会话硬 Resume。
    """

    session_id: str = ""
    seq: int = 0
    self_id: str = ""
    can_resume: bool = False
    # 官方要求鉴权后发送的第一个心跳 d 为 null。心跳任务在 Identify 之前
    # 就启动，READY 可能在首个心跳前把 seq 填上，所以用显式标记保证首个心跳
    # 一定是 null，而不是靠时序碰运气。
    heartbeat_sent: bool = False


@dataclass
class QqWsStats:
    """连接统计，仅用于日志和本地验证。"""

    connects: int = 0
    identifies: int = 0
    resumes: int = 0
    events: int = 0
    heartbeats: int = 0
    reconnects: int = 0
    last_close_code: int = 0
    failures: list[str] = field(default_factory=list)


class QqGatewayRuntime:
    """管理 QQ 网关长连接、分片与重连。"""

    def __init__(self, settings: QqWsSettings | None = None) -> None:
        self.settings = settings or QqWsSettings()
        self.stats = QqWsStats()
        self._tasks: set[asyncio.Task] = set()
        self._connections: dict[int, WebSocketConnection] = {}
        self._shutdown = asyncio.Event()
        self._intents = 0

    @property
    def running(self) -> bool:
        """当前是否已经启动连接。"""

        return bool(self._tasks)

    async def start(self, intents: int) -> None:
        """启动网关连接；重复调用不会建立第二套连接。"""

        if self._tasks:
            return

        self._intents = int(intents)
        self._shutdown.clear()
        task = asyncio.create_task(self._connect_once(), name="qq-ws-connect")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def shutdown(self) -> None:
        """停止连接与心跳，并等待后台任务退出。"""

        self._shutdown.set()
        for connection in list(self._connections.values()):
            await connection.close()
        self._connections.clear()

        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=self.settings.shutdown_grace_seconds,
                )
            except asyncio.TimeoutError:
                logger.opt(colors=True).warning(C.warn("QQ WebSocket 连接关闭等待超时"))
        self._tasks.clear()

    async def _connect_once(self) -> None:
        """获取网关地址并建立全部连接。"""

        try:
            info = await self._gateway_info()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 网关不可用时只记录并等待重启
            self._record_failure("QQ 网关地址获取失败", exc)
            return

        url = info["url"]
        shards = int(info["shards"])
        if not shards or shards < 1:
            shards = 1
        gates = info["max_concurrency"]

        logger.opt(colors=True).success(
            C.join(
                C.ok("QQ WebSocket 网关已获取"),
                C.kv("shards", shards),
                C.kv("remaining", info["remaining"]),
                C.kv("concurrency", gates),
            )
        )

        for index in range(shards):
            if self._shutdown.is_set():
                return
            task = asyncio.create_task(
                self._shard_loop(index, shards, url, info["token"]),
                name=f"qq-ws-shard-{index}",
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            if index + 1 < shards:
                # 官方要求分片建连间隔不小于 max_concurrency 秒。
                await asyncio.sleep(max(1, gates))

    async def _gateway_info(self) -> dict:
        """读取网关地址；配置了覆盖项时跳过 OpenAPI。"""

        override = gateway.gateway_url()
        if override:
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ WebSocket 网关地址已被配置覆盖"),
                    C.kv("url", override),
                )
            )
            return {
                "url": override,
                "shards": 1,
                "remaining": 1,
                "max_concurrency": 1,
                "token": await asyncio.to_thread(_access_token),
            }

        info = await asyncio.to_thread(_fetch_gateway_info)
        if int(info["remaining"]) <= 0:
            raise RuntimeError(
                "QQ 网关会话启动次数已用完，请在限额重置后再连接"
            )
        return info

    async def _shard_loop(
        self,
        shard_id: int,
        shard_count: int,
        url: str,
        access_token: str,
    ) -> None:
        """单分片的连接—鉴权—收消息—重连循环。"""

        session = QqWsSession()
        backoff = self.settings.reconnect_interval_seconds
        closed_without_ready = 0
        heartbeat_task: asyncio.Task | None = None

        while not self._shutdown.is_set():
            # 每次新建连接只送一次 Identity/Resume，心跳语义也重新开始计数。
            session.heartbeat_sent = False
            session_established = False
            connection: WebSocketConnection | None = None
            try:
                connection = await WebSocketConnection.connect(
                    url, connect_timeout=self.settings.connect_timeout_seconds
                )
                self._connections[shard_id] = connection
                self.stats.connects += 1

                interval_ms = await self._read_hello(connection)

                # 心跳必须在鉴权之前启动：官方要求鉴权后的首个心跳 d 为 null，
                # 而 READY 会立刻把 seq 填上，放到鉴权之后就会发出 d=1。
                heartbeat_task = asyncio.create_task(
                    self._heartbeat_loop(connection, session, interval_ms),
                    name=f"qq-ws-heartbeat-{shard_id}",
                )

                # 鉴权失败（服务端拒绝会话）不能在这里 continue：那会跳过
                # 下面的退避等待，把网关拖进无间隔重连。这里只记录结果，
                # 让流程落到统一的退避重连路径。
                if not await self._authenticate(
                    connection, session, access_token, (shard_id, shard_count)
                ):
                    logger.opt(colors=True).debug(
                        C.join(
                            C.ok("QQ WebSocket 会话未被接受，按退避重连"),
                            C.kv("shard", shard_id),
                        )
                    )
                else:
                    session_established = True
                    backoff = self.settings.reconnect_interval_seconds
                    await self._receive_loop(connection, session, shard_id)
            except asyncio.CancelledError:
                raise
            except WebSocketClosed as exc:
                self._handle_closed(exc, session, shard_id)
            except WebSocketProtocolError as exc:
                self._record_failure("QQ WebSocket 协议错误", exc, shard=shard_id)
            except (ConnectionError, OSError, TimeoutError) as exc:
                self._record_failure("QQ WebSocket 网络错误", exc, shard=shard_id)
            except asyncio.TimeoutError as exc:
                self._record_failure("QQ WebSocket 鉴权超时", exc, shard=shard_id)
            except Exception as exc:  # noqa: BLE001 - 未知异常也不能终止重连
                self._record_failure("QQ WebSocket 未预期错误", exc, shard=shard_id)
            finally:
                if not session_established:
                    # 只有"这次连接没能建成可用会话"才计入放弃重连的次数；
                    # 已建立过会话之后的普通断线只是需要重连，不是建连失败。
                    closed_without_ready += 1
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    await asyncio.gather(heartbeat_task, return_exceptions=True)
                    heartbeat_task = None
                self._connections.pop(shard_id, None)
                if connection is not None:
                    await connection.close()

            if self._shutdown.is_set():
                return

            self.stats.reconnects += 1
            if closed_without_ready >= self.settings.max_closed_without_ready:
                logger.opt(colors=True).warning(
                    C.join(
                        C.warn("QQ WebSocket 连续建连失败，放弃重连"),
                        C.kv("shard", shard_id),
                        C.kv("attempts", closed_without_ready),
                    )
                )
                return

            await self._sleep_before_reconnect(backoff, shard_id)
            backoff = min(
                backoff * 2, self.settings.max_reconnect_interval_seconds
            )

    async def _sleep_before_reconnect(self, delay: float, shard_id: int) -> None:
        """按退避时间等待；关闭信号可以立即打断等待。"""

        logger.opt(colors=True).debug(
            C.join(
                C.ok("QQ WebSocket 准备重连"),
                C.kv("shard", shard_id),
                C.kv("delay", f"{delay:.1f}s"),
            )
        )
        try:
            await asyncio.wait_for(
                self._shutdown.wait(), timeout=max(0.05, float(delay))
            )
        except asyncio.TimeoutError:
            return

    async def _read_hello(self, connection: WebSocketConnection) -> int:
        """读取建连后的第一条 Hello，取出心跳周期。"""

        kind, payload = await connection.receive()
        if kind != "text":
            raise WebSocketProtocolError("网关首条消息必须是文本 JSON")
        message = gateway.loads(payload)
        if gateway.payload_opcode(message) != gateway.OP_HELLO:
            raise WebSocketProtocolError(
                f"网关首条 opcode 不是 Hello：{message.get('op')!r}"
            )
        return gateway.hello_interval_ms(message)

    async def _authenticate(
        self,
        connection: WebSocketConnection,
        session: QqWsSession,
        access_token: str,
        shard: tuple[int, int],
    ) -> bool:
        """发送 Identify 或 Resume，并确认服务端接受了本次会话。"""

        if session.can_resume and session.session_id:
            self.stats.resumes += 1
            logger.opt(colors=True).debug(
                C.join(
                    C.ok("QQ WebSocket 发送 Resume"),
                    C.kv("shard", shard[0]),
                    C.kv("session", processor.short_id(session.session_id)),
                    C.kv("seq", session.seq),
                )
            )
            await connection.send_text(
                gateway.dumps(
                    gateway.build_resume(access_token, session.session_id, session.seq)
                )
            )
        else:
            self.stats.identifies += 1
            logger.opt(colors=True).debug(
                C.join(
                    C.ok("QQ WebSocket 发送 Identify"),
                    C.kv("shard", shard[0]),
                    C.kv("can_resume", session.can_resume),
                    C.kv("session", processor.short_id(session.session_id)),
                )
            )
            await connection.send_text(
                gateway.dumps(
                    gateway.build_identify(access_token, self._intents, shard)
                )
            )

        while True:
            kind, payload = await asyncio.wait_for(
                connection.receive(),
                timeout=self.settings.identify_timeout_seconds,
            )
            if kind != "text":
                continue
            message = gateway.loads(payload)
            opcode = gateway.payload_opcode(message)

            if opcode == gateway.OP_INVALID_SESSION:
                session.can_resume = gateway.invalid_session_resumable(message)
                if not session.can_resume:
                    session.session_id = ""
                logger.opt(colors=True).warning(
                    C.join(
                        C.warn("QQ 网关拒绝当前会话"),
                        C.kv("shard", shard[0]),
                        C.kv("resume", session.can_resume),
                    )
                )
                return False

            if opcode == gateway.OP_HEARTBEAT_ACK:
                continue

            if opcode != gateway.OP_DISPATCH:
                logger.opt(colors=True).warning(
                    C.join(
                        C.warn("QQ 鉴权阶段收到未知 opcode"),
                        C.kv("shard", shard[0]),
                        C.kv("op", opcode),
                    )
                )
                continue

            session.seq = gateway.payload_sequence(message, session.seq)
            event_type, _data = gateway.payload_event(message)
            if event_type == "READY":
                session_id, self_id = gateway.ready_session(message)
                session.session_id = session_id
                session.self_id = self_id
                session.can_resume = True
                logger.opt(colors=True).success(
                    C.join(
                        C.ok("QQ WebSocket 已鉴权"),
                        C.kv("shard", shard[0]),
                        C.kv("bot", processor.short_id(self_id)),
                        C.kv("session", processor.short_id(session_id)),
                    )
                )
                return True
            if event_type == "RESUMED":
                session.can_resume = True
                logger.opt(colors=True).success(
                    C.join(
                        C.ok("QQ WebSocket 会话已恢复"),
                        C.kv("shard", shard[0]),
                        C.kv("seq", session.seq),
                    )
                )
                return True

            # 鉴权期间极少出现业务事件；出现就正常派发，不丢事件。
            self._submit(message, event_type)

    async def _receive_loop(
        self,
        connection: WebSocketConnection,
        session: QqWsSession,
        shard_id: int,
    ) -> None:
        """持续接收事件，直到对端关闭或服务端要求重连。"""

        while not self._shutdown.is_set():
            kind, payload = await connection.receive()
            if kind != "text":
                continue

            message = gateway.loads(payload)
            opcode = gateway.payload_opcode(message)

            if opcode == gateway.OP_HEARTBEAT_ACK:
                continue
            if opcode == gateway.OP_RECONNECT:
                session.can_resume = True
                logger.opt(colors=True).warning(
                    C.join(
                        C.warn("QQ 网关要求重连"),
                        C.kv("shard", shard_id),
                    )
                )
                return
            if opcode == gateway.OP_INVALID_SESSION:
                session.can_resume = gateway.invalid_session_resumable(message)
                if not session.can_resume:
                    session.session_id = ""
                logger.opt(colors=True).warning(
                    C.join(
                        C.warn("QQ 网关会话失效，将重新鉴权"),
                        C.kv("shard", shard_id),
                        C.kv("resume", session.can_resume),
                    )
                )
                return
            if opcode != gateway.OP_DISPATCH:
                logger.opt(colors=True).debug(
                    C.join(
                        C.ok("QQ WebSocket 收到未知 opcode"),
                        C.kv("shard", shard_id),
                        C.kv("op", opcode),
                    )
                )
                continue

            session.seq = gateway.payload_sequence(message, session.seq)
            event_type, _data = gateway.payload_event(message)
            if event_type == "READY":
                session_id, self_id = gateway.ready_session(message)
                session.session_id = session_id or session.session_id
                session.self_id = self_id or session.self_id
                session.can_resume = True
                continue
            if event_type == "RESUMED":
                session.can_resume = True
                continue
            self._submit(message, event_type)

    async def _heartbeat_loop(
        self,
        connection: WebSocketConnection,
        session: QqWsSession,
        interval_ms: int,
    ) -> None:
        """按 Hello 给出的周期发送心跳。"""

        interval = max(1.0, interval_ms / 1000.0)
        while True:
            try:
                heartbeat_seq = session.seq if session.heartbeat_sent else None
                await connection.send_text(
                    gateway.dumps(gateway.build_heartbeat(heartbeat_seq))
                )
                session.heartbeat_sent = True
                self.stats.heartbeats += 1
            except (WebSocketClosed, WebSocketProtocolError, ConnectionError, OSError):
                return
            await asyncio.sleep(interval)

    def _submit(self, payload: dict, event_type: str) -> None:
        """把 op 0 事件解析成规整事件并送入共享队列。"""

        event = processor.parse_gateway_event(payload, event_type)
        if event is None:
            logger.opt(colors=True).debug(
                C.join(
                    C.ok("QQ WebSocket 事件已忽略"),
                    C.kv("type", event_type or "-"),
                    C.kv("event", processor.short_id(payload.get("id"))),
                )
            )
            return

        self.stats.events += 1
        logger.opt(colors=True).debug(
            C.join(
                C.ok("QQ WebSocket 已接收"),
                *processor.event_log_parts(event, include_message=False),
            )
        )
        processor.driver_runtime.enqueue_interaction_ack(event)
        asyncio.create_task(self._enqueue(event), name="qq-ws-enqueue")

    async def _enqueue(self, event: QqMessageEvent) -> None:
        """把事件送入共享队列，并兜住入队异常。"""

        try:
            await processor.submit_event(event)
        except Exception as exc:  # noqa: BLE001 - 单条事件不能打断接收循环
            self._record_failure("QQ WebSocket 事件入队失败", exc)

    def _handle_closed(
        self, exc: WebSocketClosed, session: QqWsSession, shard_id: int
    ) -> None:
        """处理一次对端关闭。

        这段必须自己兜住异常：它运行在 `except` 分支里，任何未捕获的异常都会
        直接终止整个分片任务，而分片任务正是负责重连的那个任务。关闭码解释
        出错只应退化成"重新 Identify"，不能变成永久掉线。
        """

        try:
            self._apply_close_code(exc.close_code, session)
        except Exception as error:  # noqa: BLE001 - 关闭码解释失败不能杀死重连
            session.can_resume = False
            session.session_id = ""
            self._record_failure("QQ WebSocket 关闭码处理失败", error, shard=shard_id)
        finally:
            self.stats.last_close_code = exc.close_code
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ WebSocket 连接已断开，准备重连"),
                    C.kv("shard", shard_id),
                    C.kv("code", exc.close_code),
                    C.kv("resume", session.can_resume),
                )
            )

    def _apply_close_code(self, close_code: int, session: QqWsSession) -> None:
        """按关闭码决定下一次连接是 Resume 还是重新 Identify。"""

        if close_code in gateway.FATAL_CLOSE_CODES:
            session.can_resume = False
            session.session_id = ""
            logger.opt(colors=True).error(
                C.join(
                    C.fail("QQ WebSocket 连接被平台拒绝，已停止重连"),
                    C.kv("code", close_code),
                )
            )
            self._shutdown.set()
            return

        if close_code in gateway.RESUMABLE_CLOSE_CODES:
            session.can_resume = True
            return

        # 1000/1006 等普通断开说明本机与服务端之间的链路出了问题，会话本身
        # 未必失效，官方允许 Resume 补发遗漏事件；其余 4xxx 是服务端明确判定
        # 会话不可用，必须丢弃会话重新 Identify，硬 Resume 只会再被拒一次。
        if close_code in gateway.RECONNECT_CLOSE_CODES:
            # 服务端若已经在 op 9 里明确说过"可以 Resume"（d=true），这个结论
            # 比本地链路断开码更有信息量，不能被覆盖掉。
            if not session.can_resume:
                session.can_resume = bool(session.session_id)
            return

        session.can_resume = False
        session.session_id = ""

    def _record_failure(self, title: str, exc: BaseException, *, shard: int | None = None) -> None:
        """记录一次连接级失败，不抛给调用方。"""

        detail = f"{type(exc).__name__}: {exc}"
        self.stats.failures.append(detail)
        parts = [C.fail(title)]
        if shard is not None:
            parts.append(C.kv("shard", shard))
        logger.opt(colors=True, exception=exc).warning(C.join(*parts))


def _fetch_gateway_info() -> dict:
    """在线程中调用 OpenAPI 获取网关地址，避免阻塞事件循环。"""

    from ..qq_protocol.client import client

    return client.get_gateway_info()


def _access_token() -> str:
    """读取一次 access token，供覆盖网关地址时的鉴权使用。"""

    from ..qq_protocol.client import client

    return client.get_access_token()


__all__ = ["QqGatewayRuntime", "QqWsSession", "QqWsSettings", "QqWsStats"]
