"""QQ 网关 WebSocket 连接运行时。

只负责"把网关上的字节变成 `QqMessageEvent` 并交给共用队列"这一段：
建连、Hello、Identify/Resume、心跳、分片、重连退避和关闭清理。

重连时会重新读取网关信息并现取 access token；连续鉴权失败进入长冷却
后继续，而不是永久退出。这样启动时缓存的 token/地址不会在两小时后
被复用，也不会因为一次平台抖动把整个分片任务结束掉。

命令匹配、守卫、业务回调与回复发送全部复用 `launch.adapter.qq_protocol`，
本文件不重复实现；底层帧与连接由框架级 `launch.adapter.websocket` 提供。
官方连接维护语义见
https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/event-emit.html
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field, replace

from launch.log import C, logger

from ..qq_protocol import processor
from ..qq_protocol.event import QqMessageEvent
from ..websocket import WebSocketClosed, WebSocketConnection, WebSocketProtocolError
from . import gateway

TRANSPORT = "websocket"

# 鉴权结果：区分正常、可恢复的会话失效和不可恢复的会话失效，
# 重连循环据此决定是换凭据立即重试，还是进入退避。
AUTH_READY = "ready"
AUTH_RESUMED = "resumed"
AUTH_INVALID_RESUMABLE = "invalid_resumable"
AUTH_INVALID_FATAL = "invalid_fatal"


@dataclass(frozen=True)
class QqWsSettings:
    """WebSocket 传输自己的连接参数。

    重连退避从 3 秒起步翻倍到 60 秒封顶；连续建连失败达到阈值后进入
    auth_failure_cooldown_seconds 长冷却，之后继续，不永久退出。
    """

    reconnect_interval_seconds: float = 3.0
    max_reconnect_interval_seconds: float = 60.0
    identify_timeout_seconds: float = 15.0
    connect_timeout_seconds: float = 15.0
    shutdown_grace_seconds: float = 3.0
    max_closed_without_ready: int = 8
    # 网关信息缓存时间；token 不缓存，每次连接前现取。
    gateway_cache_seconds: float = 60.0
    # 连续建连失败多少次后进入长冷却，而不是永久退出。
    auth_failure_cooldown_seconds: float = 300.0


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
    auth_rejections: int = 0
    gateway_refreshes: int = 0
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
        self._gateway_cache: dict[str, object] | None = None
        self._gateway_cache_at = 0.0
        self._gateway_lock = asyncio.Lock()
        self._override_logged = False

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
        """获取网关地址并建立全部分片；取不到就继续退避，不永久退出。"""

        backoff = self.settings.reconnect_interval_seconds
        while not self._shutdown.is_set():
            try:
                info = await self._gateway_info(force=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 网关不可用时继续等
                self._record_failure("QQ 网关地址获取失败", exc)
                await self._sleep_before_reconnect(backoff, None)
                backoff = min(
                    backoff * 2, self.settings.max_reconnect_interval_seconds
                )
                continue

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
                    self._shard_loop(index, shards),
                    name=f"qq-ws-shard-{index}",
                )
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
                if index + 1 < shards:
                    # 官方要求分片建连间隔不小于 max_concurrency 秒。
                    await asyncio.sleep(max(1, gates))
            return

    async def _gateway_info(self, *, force: bool = False) -> dict:
        """读取网关地址；覆盖项固定，否则按 gateway_cache_seconds 缓存。

        token 不在这里返回：它属于鉴权凭据，必须每次连接前现取，
        不能把启动时的那一份复用到两小时后的重连上。
        """

        override = gateway.gateway_url()
        if override:
            if not self._override_logged:
                logger.opt(colors=True).warning(
                    C.join(
                        C.warn("QQ WebSocket 网关地址已被配置覆盖"),
                        C.kv("url", override),
                    )
                )
                self._override_logged = True
            return {
                "url": override,
                "shards": 1,
                "remaining": 1,
                "max_concurrency": 1,
            }

        async with self._gateway_lock:
            now = time.monotonic()
            if (
                not force
                and self._gateway_cache is not None
                and now - self._gateway_cache_at < self.settings.gateway_cache_seconds
            ):
                return self._gateway_cache

            info = await asyncio.to_thread(_fetch_gateway_info)
            remaining = int(info["remaining"])
            if remaining <= 0:
                # 不能把“启动次数为 0”的旧缓存留着，否则下一轮会拿它
                # 继续判断为可用。
                self._gateway_cache = None
                raise RuntimeError(
                    "QQ 网关会话启动次数已用完，请在限额重置后再连接"
                )
            self._gateway_cache = dict(info)
            self._gateway_cache_at = time.monotonic()
            self.stats.gateway_refreshes += 1
            return self._gateway_cache

    async def _shard_loop(self, shard_id: int, shard_count: int) -> None:
        """单分片的连接—鉴权—收消息—重连循环。"""

        session = QqWsSession()
        backoff = self.settings.reconnect_interval_seconds
        closed_without_ready = 0
        auth_retry_used = False
        heartbeat_task: asyncio.Task | None = None

        while not self._shutdown.is_set():
            # 每次新建连接只送一次 Identity/Resume，心跳语义也重新开始计数。
            session.heartbeat_sent = False
            session_established = False
            connection: WebSocketConnection | None = None
            retry_now = False
            try:
                # 每次重连都重新看网关信息并取 token；token 的过期刷新在
                # client.get_access_token() 里，不能只在启动时取一次。
                info = await self._gateway_info(force=auth_retry_used)
                token = await asyncio.to_thread(_access_token)
                connection = await WebSocketConnection.connect(
                    str(info["url"]),
                    connect_timeout=self.settings.connect_timeout_seconds,
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

                result = await self._authenticate(
                    connection, session, token, (shard_id, shard_count)
                )
                if result in (AUTH_READY, AUTH_RESUMED):
                    session_established = True
                    auth_retry_used = False
                    closed_without_ready = 0
                    backoff = self.settings.reconnect_interval_seconds
                    await self._receive_loop(connection, session, shard_id)
                else:
                    # 鉴权被拒：会话和 token 都可能已经失效，先清 token、
                    # 丢弃网关缓存；第一次再给一次立即重试的机会。
                    self.stats.auth_rejections += 1
                    _clear_access_token()
                    self._gateway_cache = None
                    if not auth_retry_used:
                        auth_retry_used = True
                        retry_now = True
                    logger.opt(colors=True).warning(
                        C.join(
                            C.warn("QQ WebSocket 鉴权被拒，准备换凭据重试"),
                            C.kv("shard", shard_id),
                            C.kv("retry_now", retry_now),
                        )
                    )
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

            if retry_now:
                # 第一次鉴权被拒：token 已清、网关缓存已失效，立即再试一次；
                # 第二次再拒就走退避，不能在这里空转。
                logger.opt(colors=True).warning(
                    C.join(
                        C.warn("QQ WebSocket 刷新凭据后立即重试"),
                        C.kv("shard", shard_id),
                    )
                )
                continue

            self.stats.reconnects += 1
            if closed_without_ready >= self.settings.max_closed_without_ready:
                logger.opt(colors=True).warning(
                    C.join(
                        C.warn("QQ WebSocket 连续建连失败，进入长冷却"),
                        C.kv("shard", shard_id),
                        C.kv("attempts", closed_without_ready),
                        C.kv(
                            "cooldown",
                            f"{self.settings.auth_failure_cooldown_seconds:.0f}s",
                        ),
                    )
                )
                await self._sleep_before_reconnect(
                    self.settings.auth_failure_cooldown_seconds, shard_id
                )
                closed_without_ready = 0
                auth_retry_used = False
                backoff = self.settings.reconnect_interval_seconds
                continue

            await self._sleep_before_reconnect(backoff, shard_id)
            backoff = min(
                backoff * 2, self.settings.max_reconnect_interval_seconds
            )

    async def _sleep_before_reconnect(
        self, delay: float, shard_id: int | None
    ) -> None:
        """按退避时间等待；关闭信号可以立即打断等待。"""

        parts = [C.ok("QQ WebSocket 准备重连")]
        if shard_id is not None:
            parts.append(C.kv("shard", shard_id))
        parts.append(C.kv("delay", f"{delay:.1f}s"))
        logger.opt(colors=True).debug(C.join(*parts))
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
    ) -> str:
        """发送 Identify 或 Resume，返回鉴权结果。"""

        if session.can_resume and session.session_id:
            self.stats.resumes += 1
            logger.opt(colors=True).debug(
                C.join(
                    C.ok("QQ WebSocket 发送 Resume"),
                    C.kv("shard", shard[0]),
                    C.kv("session", session.session_id or "-"),
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
                    C.kv("session", session.session_id or "-"),
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
                return (
                    AUTH_INVALID_RESUMABLE
                    if session.can_resume
                    else AUTH_INVALID_FATAL
                )

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
                        C.kv("bot", self_id or "-"),
                        C.kv("session", session_id or "-"),
                    )
                )
                return AUTH_READY
            if event_type == "RESUMED":
                session.can_resume = True
                logger.opt(colors=True).success(
                    C.join(
                        C.ok("QQ WebSocket 会话已恢复"),
                        C.kv("shard", shard[0]),
                        C.kv("seq", session.seq),
                    )
                )
                return AUTH_RESUMED

            # 鉴权期间极少出现业务事件；出现就正常派发，不丢事件。
            self._submit(message, event_type, session.self_id or "qq_ws")

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
                # 这是网关的正常控制帧，不是错误；降到 INFO，避免用户把
                # “要求换连接”误读成掉线。
                logger.opt(colors=True).info(
                    C.join(
                        C.ok("QQ 网关要求重连"),
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
            self._submit(message, event_type, session.self_id or "qq_ws")

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

    def _submit(self, payload: dict, event_type: str, bot_key: str) -> None:
        """把 op 0 事件解析成规整事件并送入共享队列。"""

        event = processor.parse_gateway_event(payload, event_type)
        if event is None:
            logger.opt(colors=True).debug(
                C.join(
                    C.ok("QQ WebSocket 事件已忽略"),
                    C.kv("type", event_type or "-"),
                    C.kv("event", payload.get("id") or "-"),
                )
            )
            return

        event = replace(event, transport=TRANSPORT, bot_key=bot_key)
        self.stats.events += 1
        logger.opt(colors=True).debug(
            C.join(
                C.ok("QQ WebSocket 已接收"),
                *processor.event_log_parts(event, include_message=False),
            )
        )
        processor.driver_runtime.enqueue_interaction_ack(event)
        asyncio.create_task(self._enqueue(event, bot_key), name="qq-ws-enqueue")

    async def _enqueue(self, event: QqMessageEvent, bot_key: str) -> None:
        """把事件送入共享队列，并兜住入队异常。"""

        try:
            await processor.submit_event(
                event, transport=TRANSPORT, bot_key=bot_key
            )
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


def _clear_access_token() -> None:
    """清掉 HTTP 客户端的 token 缓存；下次 get_access_token() 会重新取。"""

    from ..qq_protocol.client import client

    client.clear_access_token()


def _access_token() -> str:
    """读取一次 access token，供覆盖网关地址时的鉴权使用。"""

    from ..qq_protocol.client import client

    return client.get_access_token()


__all__ = ["QqGatewayRuntime", "QqWsSession", "QqWsSettings", "QqWsStats"]
