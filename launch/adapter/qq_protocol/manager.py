"""QQ 回复管理器。

业务层通过统一 manager.send(...) 回复消息；QQ 驱动器在这里把业务
返回值转换成 QQ OpenAPI 可发送的载荷，并根据当前事件上下文选择
私聊或群聊接口。
"""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from launch.log import C, logger
from launch.message_events import emit_message_event, event_from_outgoing

from ..context import (
    MENTION_DEFAULT,
    MENTION_NONE,
    MENTION_SENDER,
    SendOptions,
    SendRequest,
    current_reply_target,
)
from .client import client
from .event import QqMessageEvent
from .keyboard import validate_keyboard
from .render import render_qq_message
from .target import QqSendTarget

current_event: ContextVar[QqMessageEvent | None] = ContextVar(
    "qq_current_event",
    default=None,
)


@dataclass(frozen=True)
class QqQueuedReply:
    """QQ 待发送回复。

    manager.send 只负责捕获当前事件上下文并入队；真正的 OpenAPI 请求
    由后台 worker 执行，避免业务命令被 QQ 网络耗时拖住。
    """

    message: object
    target: QqSendTarget
    user_id: str
    options: SendOptions
    is_log: bool = True
    request_id: object | None = None


class QqReplyManager:
    """按当前 QQ 事件上下文发送私聊或群聊回复。

    业务层只传入 message；QQ 真正发消息还需要知道本次
    webhook 是 C2C 还是群事件，以及原始 message_id/event_id。handler
    处理事件前会把 QqMessageEvent 放进 current_event，回复器从这里
    取 QQ 私有上下文，再调用对应 OpenAPI。
    """

    SEND_WORKERS = 8
    MAX_WAITING_REPLIES = 1000
    SHUTDOWN_DRAIN_SECONDS = 3.0

    def __init__(self) -> None:
        self._send_queue: asyncio.Queue[QqQueuedReply] | None = None
        self._send_tasks: set[asyncio.Task] = set()
        self._warmup_task: asyncio.Task | None = None
        self._send_executor: ThreadPoolExecutor | None = None

    async def start(self) -> None:
        """启动 QQ 回复发送队列，并在后台预热 access token。

        回复 worker 是固定数量的常驻协程。业务层调用 manager.send 时只入队，
        不等待 QQ OpenAPI；真正的网络请求由 worker 在后台执行。
        """

        if self._send_tasks:
            return

        self._send_executor = ThreadPoolExecutor(
            max_workers=self.SEND_WORKERS,
            thread_name_prefix="qq-send",
        )
        self._send_queue = asyncio.Queue(maxsize=self.MAX_WAITING_REPLIES)
        for index in range(self.SEND_WORKERS):
            task = asyncio.create_task(self._send_worker(index), name=f"qq-send-worker-{index}")
            self._send_tasks.add(task)
            task.add_done_callback(self._send_tasks.discard)

        if client.has_credentials:
            self._warmup_task = asyncio.create_task(
                self._warmup_access_tokens(),
                name="qq-access-token-warmup",
            )

    async def shutdown(self) -> None:
        """停止 QQ 回复发送队列，并释放 HTTP 连接池。

        关闭时先短暂等待队列清空，给已经接收的回复一个发送机会；超过
        SHUTDOWN_DRAIN_SECONDS 仍未发完，就丢弃剩余项，避免停服时一直挂住。
        """

        if self._warmup_task is not None:
            self._warmup_task.cancel()
            await asyncio.gather(self._warmup_task, return_exceptions=True)
            self._warmup_task = None

        queue = self._send_queue
        if queue is not None:
            try:
                await asyncio.wait_for(queue.join(), timeout=self.SHUTDOWN_DRAIN_SECONDS)
            except asyncio.TimeoutError:
                dropped = self._drop_waiting_replies(queue)
                logger.opt(colors=True).warning(
                    C.join(
                        C.warn("QQ 回复队列关闭等待超时，丢弃剩余回复"),
                        C.kv("dropped", dropped),
                        C.kv("waiting", queue.qsize()),
                    )
                )

        tasks = list(self._send_tasks)
        for task in tasks:
            task.cancel()

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self._send_tasks.clear()
        self._send_queue = None
        self._shutdown_executor()
        client.close()

    def _shutdown_executor(self) -> None:
        """关闭 QQ 发送专用线程池，避免 OpenAPI 线程散落到全局线程池。"""

        executor = self._send_executor
        self._send_executor = None
        if executor is None:
            return
        executor.shutdown(wait=True, cancel_futures=True)

    @staticmethod
    def _drop_waiting_replies(queue: asyncio.Queue[QqQueuedReply]) -> int:
        """丢弃还没有被 worker 取走的回复项，保证 queue.join() 不残留。"""

        dropped = 0
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return dropped

            queue.task_done()
            dropped += 1

    async def send(
        self,
        message: object,
        is_log: bool = True,
        request_id: object | None = None,
    ) -> bool:
        """发送一条 QQ 回复。

        显式主动发送使用 SendRequest.target，普通调用从当前消息上下文
        推导回复目标和关联用户。
        """

        request = self._normalize_request(message, is_log, request_id)
        target = self._send_target_from_request(request)
        if target is None:
            if request.options.log:
                logger.opt(colors=True).warning(f"{C.warn('QQ 发送失败，缺少 QQ 发送目标')}")
            return False

        item = QqQueuedReply(
            message=request.message,
            target=target,
            user_id=self._request_user_id(request, target),
            options=request.options,
            is_log=request.options.log,
            request_id=request.request_id,
        )

        queue = self._send_queue
        if queue is None:
            if is_log:
                logger.opt(colors=True).warning(
                    C.join(
                        C.warn("QQ 回复队列未启动"),
                        *self._reply_log_parts(item),
                    )
                )
            return False

        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            if is_log:
                logger.opt(colors=True).warning(
                    C.join(
                        C.warn("QQ 回复队列已满"),
                        *self._reply_log_parts(item),
                        C.kv("max_waiting", self.MAX_WAITING_REPLIES),
                    )
                )
            return False

        if is_log:
            logger.opt(colors=True).debug(
                C.join(
                    C.ok("QQ 回复已入队"),
                    *self._reply_log_parts(item),
                )
            )
        return True

    @staticmethod
    def _normalize_request(
        message: object,
        is_log: bool,
        request_id: object | None,
    ) -> SendRequest:
        """把普通 message 和显式 SendRequest 统一成发送请求。"""

        if isinstance(message, SendRequest):
            return message

        return SendRequest(
            message=message,
            target=current_reply_target(),
            options=SendOptions(log=is_log),
            request_id=request_id,
        )

    @staticmethod
    def _send_target_from_request(request: SendRequest) -> QqSendTarget | None:
        """从显式目标或当前事件中取出 QQ 发送目标。"""

        explicit_target = request.target
        if explicit_target is not None and explicit_target.adapter == "qq":
            driver_target = explicit_target.driver_target
            if isinstance(driver_target, QqSendTarget):
                return driver_target
            if isinstance(driver_target, QqMessageEvent):
                return QqSendTarget.from_event(driver_target)

        event = current_event.get()
        if isinstance(event, QqMessageEvent):
            return QqSendTarget.from_event(event)
        return None

    @staticmethod
    def _request_user_id(request: SendRequest, target: QqSendTarget) -> str:
        """读取本次发送关联的统一游戏用户编号。"""

        reply_target = request.target
        if reply_target is not None and reply_target.user_id:
            return str(reply_target.user_id)
        event = current_event.get()
        if event is not None and event.user_id:
            return event.user_id
        return target.user_id

    async def _send_worker(self, index: int) -> None:
        """后台发送 QQ 回复。

        worker 自己兜住单条发送异常，避免某次 OpenAPI 报错把整个发送协程
        打死。只有 shutdown cancel 时才退出循环。
        """

        queue = self._send_queue
        if queue is None:
            return

        try:
            while True:
                item = await queue.get()
                try:
                    await self._send_direct(item)
                except Exception as exc:  # noqa: BLE001 - 单条发送失败不能终止 worker
                    logger.opt(colors=True, exception=exc).warning(
                        C.join(
                            C.warn("QQ 回复 worker 异常"),
                            C.kv("worker", index),
                        )
                    )
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            return

    async def _warmup_access_tokens(self) -> None:
        """后台预热唯一 QQ bot 的 access token。"""

        try:
            await self._run_sync(client.get_access_token)
            logger.opt(colors=True).debug(f"{C.ok('QQ access token 已预热')}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 预热失败不能阻止服务启动
            logger.opt(colors=True, exception=exc).warning(f"{C.warn('QQ access token 预热失败')}")

    async def _send_direct(self, item: QqQueuedReply) -> bool:
        """执行一次 QQ 回复发送，供队列 worker 和兜底路径共用。"""

        try:
            payload = await self._run_sync(
                self._send_sync,
                item.message,
                item.target,
                item.options,
            )
        except Exception as exc:  # noqa: BLE001 - QQ 客户端错误统一转换为发送失败
            logger.opt(colors=True, exception=exc).warning(
                C.join(
                    C.warn("QQ 回复发送失败"),
                    *self._reply_log_parts(item),
                )
            )
            return False

        if not payload:
            return False

        emit_message_event(
            event_from_outgoing(
                adapter="qq",
                user_id=item.user_id,
                request_id=item.request_id or item.target.event_id or item.target.message_id,
                message=item.message,
            )
        )

        if item.is_log:
            logger.opt(colors=True).debug(
                C.join(
                    C.ok("QQ 回复已发送"),
                    *self._reply_log_parts(item),
                    C.kv("msg_type", payload.get("msg_type") or "-"),
                )
            )
        return True

    async def _run_sync(self, func, *args):
        """在 QQ 发送专用线程池里运行同步 OpenAPI 调用。

        发送链路必须走本驱动器自己的线程池，便于统一关闭和排查线程残留。
        如果这里没有线程池，说明 manager.start() 没有按生命周期执行。
        """

        executor = self._send_executor
        if executor is None:
            raise RuntimeError("QQ 发送线程池未启动")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, func, *args)

    @staticmethod
    def _send_sync(
        message: object,
        target: QqMessageEvent | QqSendTarget,
        options: SendOptions | None = None,
    ) -> dict:
        """在线程中执行 QQ OpenAPI 调用，避免阻塞 async 事件循环。"""

        send_target = QqSendTarget.from_event(target) if isinstance(target, QqMessageEvent) else target
        options = options or SendOptions()
        payload = QqReplyManager._message_payload(message, send_target, options)
        if not payload:
            return {}

        if send_target.is_group:
            client.send_group_payload(
                send_target.group_id,
                payload,
                send_target.message_id,
                send_target.event_id,
            )
        else:
            client.send_c2c_payload(
                send_target.user_id,
                payload,
                send_target.message_id,
                send_target.event_id,
                is_wakeup=send_target.is_wakeup,
            )
        return payload

    @staticmethod
    def _reply_log_parts(item: QqQueuedReply) -> list[str]:
        """生成 QQ 回复日志摘要。"""

        return [
            C.kv("type", "群聊" if item.target.is_group else "私聊"),
            C.kv("user", QqReplyManager._short_id(item.user_id)),
            C.kv(
                "target",
                QqReplyManager._short_id(
                    item.target.group_id or item.target.user_id
                ),
            ),
            C.kv("request_id", item.request_id or "-"),
        ]

    @staticmethod
    def _message_payload(message: object, target: QqSendTarget, options: SendOptions) -> dict:
        """把业务返回值转换成 QQ OpenAPI 消息载荷。

        QQ 驱动器内部协议使用 kind 字段表达官方发送能力。业务组件
        当前只使用 markdown/image，驱动器本身仍覆盖 text/ark/embed/media/raw。
        """

        message = render_qq_message(message)
        if isinstance(message, dict):
            return QqReplyManager._apply_mention(
                QqReplyManager._payload_from_kind(message, target),
                target,
                options,
            )

        content = QqReplyManager._message_text(message)
        return QqReplyManager._apply_mention(QqReplyManager._text_payload(content), target, options)

    @staticmethod
    def _payload_from_kind(message: dict, target: QqSendTarget) -> dict:
        """按 QQ 驱动器 kind 协议生成官方 OpenAPI payload。"""

        kind = str(message.get("kind") or "").strip().lower()
        if not kind:
            if "msg_type" in message:
                return dict(message)
            raise ValueError("QQ 回复协议缺少 kind 字段")

        if kind == "text":
            return QqReplyManager._with_common_fields(
                QqReplyManager._text_payload(QqReplyManager._message_text(message.get("content"))),
                message,
            )
        if kind == "markdown":
            return QqReplyManager._with_common_fields(QqReplyManager._markdown_payload(message), message)
        if kind == "image":
            return QqReplyManager._with_common_fields(
                QqReplyManager._image_payload(message.get("image"), target, message.get("content")),
                message,
            )
        if kind == "media":
            return QqReplyManager._with_common_fields(QqReplyManager._media_payload(message), message)
        if kind == "ark":
            return QqReplyManager._with_common_fields(QqReplyManager._ark_payload(message), message)
        if kind == "embed":
            return QqReplyManager._with_common_fields(QqReplyManager._embed_payload(message), message)
        if kind == "raw":
            raw_payload = message.get("payload")
            if not isinstance(raw_payload, dict):
                raise ValueError("QQ raw 回复缺少 payload 对象")
            return dict(raw_payload)
        raise ValueError(f"QQ 回复协议 kind 不支持：{kind}")

    @staticmethod
    def _markdown_payload(message: dict) -> dict:
        """生成 QQ markdown 消息载荷，保留业务层已经生成的按钮。"""

        markdown = dict(message.get("markdown") or {}) if isinstance(message.get("markdown"), dict) else {}
        content = str(message.get("content") or markdown.get("content") or "").strip()
        if content:
            markdown["content"] = content
        if not markdown:
            return {}

        payload: dict[str, Any] = {
            "content": " ",
            "msg_type": 2,
            "markdown": markdown,
        }
        keyboard = message.get("keyboard")
        if QqReplyManager._has_keyboard_buttons(keyboard):
            payload["keyboard"] = validate_keyboard(keyboard)
        return payload

    @staticmethod
    def _image_payload(message: object, target: QqSendTarget, content: object = None) -> dict:
        """生成 QQ 纯图片消息载荷。

        QQ 纯图片回复不能直接把 BytesIO/bytes 塞进发消息接口，需要先上传
        到当前会话的 /files 接口拿 file_info，再用 msg_type=7 发送 media。
        """

        image_bytes = QqReplyManager._read_image_bytes(message)
        if not image_bytes:
            raise ValueError("QQ 图片消息内容为空或格式不支持")

        if target.is_group:
            file_info = client.upload_group_image(target.group_id, image_bytes)
        else:
            file_info = client.upload_c2c_image(target.user_id, image_bytes)

        return {
            "content": str(content or " "),
            "msg_type": 7,
            "media": {"file_info": file_info},
        }

    @staticmethod
    def _media_payload(message: dict) -> dict:
        """生成 QQ 富媒体 payload。"""

        media = message.get("media")
        if isinstance(media, str):
            media = {"file_info": media}
        if not isinstance(media, dict) or not media:
            return {}
        return {
            "content": str(message.get("content") or " "),
            "msg_type": 7,
            "media": dict(media),
        }

    @staticmethod
    def _ark_payload(message: dict) -> dict:
        """生成 QQ Ark payload。"""

        ark = message.get("ark")
        if not isinstance(ark, dict) or not ark:
            return {}
        return {
            "content": str(message.get("content") or " "),
            "msg_type": 3,
            "ark": dict(ark),
        }

    @staticmethod
    def _embed_payload(message: dict) -> dict:
        """生成 QQ Embed payload。"""

        embed = message.get("embed")
        if not isinstance(embed, dict) or not embed:
            return {}
        return {
            "content": str(message.get("content") or " "),
            "msg_type": 4,
            "embed": dict(embed),
        }

    @staticmethod
    def _with_common_fields(payload: dict, message: dict) -> dict:
        """附加 QQ 官方通用发送字段。"""

        if not payload:
            return payload
        result = dict(payload)
        message_reference = message.get("message_reference")
        if isinstance(message_reference, dict) and message_reference:
            result["message_reference"] = dict(message_reference)
        if message.get("msg_seq") is not None:
            result["msg_seq"] = int(message["msg_seq"])
        return result

    @staticmethod
    def _text_payload(content: str) -> dict:
        """生成 QQ 普通文本消息载荷。"""

        content = str(content).strip()
        if not content:
            return {}
        return {
            "content": content,
            "msg_type": 0,
        }

    @staticmethod
    def _apply_mention(payload: dict, target: QqSendTarget, options: SendOptions) -> dict:
        """按发送选项给群消息补 at。"""

        mention_user_id = QqReplyManager._mention_user_id(target, options)
        if not payload or not mention_user_id:
            return payload

        mention_text = f"<@{mention_user_id}>"
        result = dict(payload)
        msg_type = int(result.get("msg_type") or 0)

        if msg_type == 2 and isinstance(result.get("markdown"), dict):
            markdown = dict(result["markdown"])
            markdown["content"] = QqReplyManager._prepend_mention(
                mention_text,
                str(markdown.get("content") or ""),
            )
            result["markdown"] = markdown
            result["content"] = mention_text
            return result

        result["content"] = QqReplyManager._prepend_mention(
            mention_text,
            str(result.get("content") or ""),
        )
        return result

    @staticmethod
    def _mention_user_id(target: QqSendTarget, options: SendOptions) -> str:
        """计算本次群消息需要 at 的 user_id。"""

        if not target.is_group:
            return ""

        value = str(options.mention or MENTION_DEFAULT).strip()
        if not value or value in {MENTION_DEFAULT, MENTION_NONE}:
            return ""
        if value == MENTION_SENDER:
            return target.user_id
        if value.startswith("<@") and value.endswith(">"):
            value = value[2:-1]
        return value.strip().lstrip("!")

    @staticmethod
    def _prepend_mention(mention_text: str, content: str) -> str:
        """把 at 放在正文开头，避免重复添加。"""

        text = str(content or "").strip()
        if not text:
            return mention_text
        if text.startswith(mention_text):
            return text
        return f"{mention_text} {text}".strip()

    @staticmethod
    def _message_text(message: object) -> str:
        """把非 markdown 回复整理成普通文本。"""

        if isinstance(message, dict):
            if "content" in message:
                return str(message.get("content") or "").strip()
            return json.dumps(message, ensure_ascii=False, default=str)
        if isinstance(message, (list, tuple)):
            return "\n".join(str(item) for item in message if str(item).strip()).strip()
        if message is None:
            return ""
        return str(message).strip()

    @staticmethod
    def _read_image_bytes(message: object) -> bytes:
        """读取图片二进制，支持 bytes、BytesIO 和 Path。"""

        if isinstance(message, bytes):
            return message
        if isinstance(message, bytearray | memoryview):
            return bytes(message)
        if isinstance(message, BytesIO):
            position = message.tell()
            message.seek(0)
            data = message.read()
            message.seek(position)
            return data
        if isinstance(message, Path):
            return message.read_bytes()
        if hasattr(message, "read"):
            return QqReplyManager._read_file_like_bytes(message)
        return b""

    @staticmethod
    def _read_file_like_bytes(message: object) -> bytes:
        """读取类文件对象，尽量恢复原始指针位置。"""

        position = None
        try:
            if hasattr(message, "tell"):
                position = message.tell()
            if hasattr(message, "seek"):
                message.seek(0)
            data = message.read()
        finally:
            if position is not None and hasattr(message, "seek"):
                message.seek(position)

        if isinstance(data, str):
            return data.encode("utf-8")
        if isinstance(data, bytes):
            return data
        if isinstance(data, bytearray | memoryview):
            return bytes(data)
        return b""

    @staticmethod
    def _has_keyboard_buttons(value: object) -> bool:
        """判断 QQ keyboard 中是否真的有按钮，避免发送空键盘。"""

        if not isinstance(value, dict):
            return False
        if value.get("id"):
            return True
        content = value.get("content", {})
        if not isinstance(content, dict):
            return False
        rows = content.get("rows", [])
        if not isinstance(rows, list):
            return False
        return any(
            isinstance(row, dict) and bool(row.get("buttons"))
            for row in rows
        )

    @staticmethod
    def _short_id(value: object, head: int = 8, tail: int = 6) -> str:
        """缩短开放平台长 ID，避免正常回复日志过长。"""

        text = str(value or "").strip()
        if not text:
            return "-"
        if len(text) <= head + tail + 3:
            return text
        return f"{text[:head]}...{text[-tail:]}"


manager = QqReplyManager()
