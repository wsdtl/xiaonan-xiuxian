"""QQ OpenAPI 客户端。

本文件只封装主动调用 QQ 开放接口的细节，包括获取 app access token
和发送消息。驱动器的 webhook 接收、事件排队和命令派发不放在这里。
"""

import json
import time
from base64 import b64encode
from threading import Lock
from typing import Any

import urllib3
from urllib3.exceptions import (
    ConnectTimeoutError,
    NewConnectionError,
)
from urllib3.exceptions import (
    HTTPError as Urllib3Error,
)

from launch.config import config
from launch.log import C, logger

QQ_TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
QQ_OPEN_API_BASE = "https://api.sgroup.qq.com"

# QQ OpenAPI 是回复链路里最慢、最不稳定的一段。这里把超时拆成连接超时
# 和读取超时：连接失败尽快返回，已连上后给平台留出正常处理时间。
QQ_HTTP_CONNECT_TIMEOUT_SECONDS = 3.0
QQ_HTTP_READ_TIMEOUT_SECONDS = 8.0

# 连接池上限需要和 manager.SEND_WORKERS 保持同一个数量级。设得太大会在
# QQ OpenAPI 慢时占用过多本机连接，设得太小又会让后台发送 worker 互相排队。
QQ_HTTP_POOL_SIZE = 16
QQ_OPENAPI_MAX_TRANSIENT_RETRIES = 2
QQ_OPENAPI_MAX_RETRY_DELAY_SECONDS = 5.0
QQ_OPENAPI_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class QqOpenApiClient:
    """QQ 驱动器内部使用的开放接口客户端。

    这个类只负责主动调用 QQ OpenAPI：获取 app access token、发送 C2C
    消息、发送群消息。事件接收、命令匹配和业务调度都在 handler.py，
    不在这里混入。
    """

    def __init__(
        self,
        app_id: str | None = None,
        client_secret: str | None = None,
    ) -> None:
        self.api_base = QQ_OPEN_API_BASE.rstrip("/")
        self.app_id = config.get("QQ_BOT_APP_ID", "").strip() if app_id is None else str(app_id or "").strip()
        self.client_secret = config.get("QQ_BOT_SECRET", "").strip() if client_secret is None else str(client_secret or "").strip()
        self._access_token = ""
        self._access_token_expires_at = 0.0
        self._access_token_lock = Lock()
        self._sleep = time.sleep
        self._http = urllib3.PoolManager(
            num_pools=4,
            maxsize=QQ_HTTP_POOL_SIZE,
            block=True,
            timeout=urllib3.Timeout(
                connect=QQ_HTTP_CONNECT_TIMEOUT_SECONDS,
                read=QQ_HTTP_READ_TIMEOUT_SECONDS,
            ),
        )

    def send_c2c_payload(
        self,
        user_id: str,
        payload: dict,
        message_id: str = "",
        event_id: str = "",
        is_wakeup: bool = False,
    ) -> dict:
        """按 QQ OpenAPI 消息载荷回复 C2C 私聊消息。"""

        return self._post_openapi(
            f"/v2/users/{user_id}/messages",
            self._reply_payload(payload, message_id, event_id, is_wakeup=is_wakeup),
        )

    def ack_interaction(self, interaction_id: str, code: int = 0) -> dict:
        """确认 QQ 按钮回调，避免客户端点击后一直等待。"""

        value = str(interaction_id or "").strip()
        if not value:
            return {}
        return self._put_openapi(
            f"/interactions/{value}",
            {"code": int(code)},
            log_title="QQ 按钮回调已确认",
        )

    def get_gateway_info(self) -> dict:
        """获取 WebSocket 网关地址、分片建议和连接数限制。

        这是 WebSocket 传输唯一的建连前置请求，走同一条 OpenAPI 鉴权和
        重试规则，因此 access token 与 HTTP 连接池和回复链路完全共用。
        """

        result = self._get_openapi("/gateway/bot", log_title="QQ 网关地址获取成功")
        url = str(result.get("url") or "").strip()
        if not url:
            raise RuntimeError(
                f"QQ 网关接口未返回 url：{json.dumps(result, ensure_ascii=False)}"
            )

        limit = (
            result.get("session_start_limit")
            if isinstance(result.get("session_start_limit"), dict)
            else {}
        )
        shards = _positive_int(result.get("shards"), 1)
        return {
            "url": url,
            "shards": shards,
            "remaining": _positive_int(limit.get("remaining"), 0, allow_zero=True),
            "max_concurrency": _positive_int(limit.get("max_concurrency"), 1),
        }

    def upload_c2c_image(self, user_id: str, image_bytes: bytes) -> str:
        """上传 C2C 私聊图片，返回发消息接口可使用的 file_info。"""

        return self._upload_image_file_info(f"/v2/users/{user_id}/files", image_bytes)

    def send_group_payload(
        self,
        group_id: str,
        payload: dict,
        message_id: str = "",
        event_id: str = "",
    ) -> dict:
        """按 QQ OpenAPI 消息载荷回复群消息。"""

        return self._post_openapi(
            f"/v2/groups/{group_id}/messages",
            self._reply_payload(payload, message_id, event_id),
        )

    def upload_group_image(self, group_id: str, image_bytes: bytes) -> str:
        """上传群聊图片，返回发消息接口可使用的 file_info。"""

        return self._upload_image_file_info(f"/v2/groups/{group_id}/files", image_bytes)

    @staticmethod
    def _reply_payload(
        payload: dict,
        message_id: str = "",
        event_id: str = "",
        *,
        is_wakeup: bool = False,
    ) -> dict[str, Any]:
        """补齐回复消息必须携带的 msg_id 和可选 event_id。"""

        result: dict[str, Any] = dict(payload)
        if message_id:
            result["msg_id"] = message_id
        if event_id:
            result["event_id"] = event_id
        if is_wakeup:
            result["is_wakeup"] = True
        return result

    def _upload_image_file_info(self, path: str, image_bytes: bytes) -> str:
        """把本地图片二进制上传成 QQ 富媒体 file_info。"""

        if not image_bytes:
            raise ValueError("QQ 图片内容为空")

        result = self._post_openapi(
            path,
            {
                "file_type": 1,
                "file_data": b64encode(image_bytes).decode("ascii"),
                "srv_send_msg": False,
            },
            log_title="QQ 图片上传成功",
        )
        file_info = str(result.get("file_info") or "").strip()
        if not file_info:
            raise RuntimeError(f"QQ 图片上传未返回 file_info：{json.dumps(result, ensure_ascii=False)}")
        return file_info

    def _post_openapi(self, path: str, payload: dict, log_title: str = "QQ 发消息成功") -> dict:
        """调用 QQ OpenAPI，遇到 token 失效时刷新后重试一次。"""

        return self._request_openapi("POST", path, payload, log_title)

    def _get_openapi(self, path: str, log_title: str) -> dict:
        """调用 QQ OpenAPI 的 GET 接口。"""

        return self._request_openapi("GET", path, {}, log_title)

    def _put_openapi(self, path: str, payload: dict, log_title: str) -> dict:
        """调用 QQ OpenAPI PUT 接口，遇到 token 失效时刷新后重试一次。"""

        return self._request_openapi("PUT", path, payload, log_title)

    def _request_openapi(self, method: str, path: str, payload: dict, log_title: str) -> dict:
        """调用 QQ OpenAPI，并对可安全重放的瞬时错误做有限重试。"""

        token_refreshed = False
        transient_retries = 0
        retry_safe = self._is_retry_safe(method, path, payload)
        while True:
            try:
                return self._request_openapi_once(method, path, payload, log_title)
            except QqOpenApiError as exc:
                if exc.status_code == 401 and not token_refreshed:
                    token_refreshed = True
                    self.clear_access_token()
                    continue
                if (
                    not retry_safe
                    or exc.status_code not in QQ_OPENAPI_RETRYABLE_STATUS_CODES
                    or transient_retries >= QQ_OPENAPI_MAX_TRANSIENT_RETRIES
                ):
                    raise
                transient_retries += 1
                self._wait_before_retry(path, exc, transient_retries)
            except QqOpenApiTransportError as exc:
                if not retry_safe or not exc.retryable or transient_retries >= QQ_OPENAPI_MAX_TRANSIENT_RETRIES:
                    raise
                transient_retries += 1
                self._wait_before_retry(path, exc, transient_retries)

    def _request_openapi_once(self, method: str, path: str, payload: dict, log_title: str) -> dict:
        """执行一次 OpenAPI 请求，不做业务层重试。"""

        token = self.get_access_token()
        status_code, raw, headers = self._request_json(
            method,
            self.api_base + path,
            payload,
            {
                "Authorization": f"QQBot {token}",
                "Content-Type": "application/json",
            },
        )
        if status_code >= 400:
            raise QqOpenApiError(status_code, raw, headers=headers)

        result = json.loads(raw) if raw else {}
        if isinstance(result, dict) and int(result.get("code") or 0) != 0:
            raise RuntimeError(f"QQ OpenAPI 返回异常：{json.dumps(result, ensure_ascii=False)}")

        logger.opt(colors=True).debug(
            C.join(
                C.ok(log_title),
                *self._openapi_result_log_parts(path, payload, result),
            )
        )
        return result

    @staticmethod
    def _is_retry_safe(method: str, path: str, payload: dict) -> bool:
        """只重试平台能按事件关联或天然幂等的请求。"""

        if str(method).upper() == "PUT":
            return True
        if str(path).rstrip("/").endswith("/files"):
            return True
        return bool(payload.get("msg_id") or payload.get("event_id"))

    def _wait_before_retry(
        self,
        path: str,
        error: "QqOpenApiError | QqOpenApiTransportError",
        attempt: int,
    ) -> None:
        delay = self._retry_delay(error, attempt)
        logger.opt(colors=True).warning(
            C.join(
                C.warn("QQ OpenAPI 瞬时失败，准备重试"),
                *self._path_log_parts(path),
                C.kv("attempt", attempt),
                C.kv("status", getattr(error, "status_code", "network")),
                C.kv("delay", f"{delay:.2f}s"),
            )
        )
        self._sleep(delay)

    @staticmethod
    def _retry_delay(
        error: "QqOpenApiError | QqOpenApiTransportError",
        attempt: int,
    ) -> float:
        if isinstance(error, QqOpenApiError):
            retry_after = error.headers.get("retry-after", "")
            try:
                if retry_after:
                    return min(
                        QQ_OPENAPI_MAX_RETRY_DELAY_SECONDS,
                        max(0.0, float(retry_after)),
                    )
            except ValueError:
                pass
        return min(QQ_OPENAPI_MAX_RETRY_DELAY_SECONDS, 0.25 * (2 ** max(0, attempt - 1)))

    def get_access_token(self) -> str:
        """获取并缓存 QQ app access token。"""

        if self._access_token and time.time() < self._access_token_expires_at - 60:
            return self._access_token

        with self._access_token_lock:
            if self._access_token and time.time() < self._access_token_expires_at - 60:
                return self._access_token

            return self._fetch_access_token()

    def clear_access_token(self) -> None:
        """清空 access token 缓存，下次请求会重新获取。"""

        with self._access_token_lock:
            self._access_token = ""
            self._access_token_expires_at = 0.0

    def close(self) -> None:
        """关闭连接池里暂存的 HTTP 连接。"""

        self._http.clear()

    @property
    def has_credentials(self) -> bool:
        """当前是否具备主动调用 QQ OpenAPI 的凭据。"""

        return bool(self.app_id and self.client_secret)

    def _fetch_access_token(self) -> str:
        """请求 QQ app access token，并更新本地缓存。"""

        if not self.app_id or not self.client_secret:
            raise RuntimeError("QQ bot 的 app_id 或 secret 未配置")

        payload = {
            "appId": self.app_id,
            "clientSecret": self.client_secret,
        }
        status_code, raw, _headers = self._request_json(
            "POST",
            QQ_TOKEN_URL,
            payload,
            {"Content-Type": "application/json"},
        )
        if status_code >= 400:
            raise RuntimeError(f"获取 QQ access_token 失败：{status_code} {raw}")

        data = json.loads(raw)
        token = str(data.get("access_token") or "").strip()
        expires_in = int(data.get("expires_in") or 0)
        if not token:
            raise RuntimeError(f"获取 QQ access_token 返回异常：{raw}")

        self._access_token = token
        self._access_token_expires_at = time.time() + expires_in
        return token

    def _request_json(
        self,
        method: str,
        url: str,
        payload: dict,
        headers: dict[str, str],
    ) -> tuple[int, str, dict[str, str]]:
        """通过连接池发送 JSON 请求，并返回状态码、响应文本和响应头。

        QQ 回复链路会频繁访问同一批域名，连接池可以复用 TLS 连接，
        避免每条消息都重新握手。这里不在 urllib3 层自动重试，业务层
        只允许 token 失效这种确定可恢复的情况重试一次。
        """

        try:
            response = self._http.request(
                method,
                url,
                body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers=headers,
                retries=False,
            )
        except Urllib3Error as exc:
            retryable = isinstance(exc, (ConnectTimeoutError, NewConnectionError))
            raise QqOpenApiTransportError(str(exc), retryable=retryable) from exc

        raw = response.data.decode("utf-8", errors="replace") if response.data else ""
        response_headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
        return int(response.status), raw, response_headers

    @staticmethod
    def _openapi_result_log_parts(path: str, payload: dict, result: object) -> list[str]:
        """生成 OpenAPI 成功日志摘要，避免把返回整包刷进日志。"""

        result_data = result if isinstance(result, dict) else {}
        if str(path).rstrip("/").endswith("/files"):
            return [
                *QqOpenApiClient._path_log_parts(path),
                C.kv("file_type", payload.get("file_type") or "-"),
                C.kv("file", QqOpenApiClient._short_id(result_data.get("file_uuid"))),
                C.kv("ttl", result_data.get("ttl", "-")),
            ]

        return [
            *QqOpenApiClient._path_log_parts(path),
            C.kv("msg_type", payload.get("msg_type") or "-"),
            C.kv("msg", QqOpenApiClient._short_id(payload.get("msg_id"))),
            C.kv(
                "result",
                QqOpenApiClient._short_id(
                    result_data.get("id")
                    or result_data.get("message_id")
                    or result_data.get("msg_id")
                ),
            ),
        ]

    @staticmethod
    def _path_log_parts(path: str) -> list[str]:
        """从 OpenAPI path 中提取发送目标类型和目标 ID。"""

        parts = [part for part in str(path).strip("/").split("/") if part]
        if len(parts) >= 4 and parts[-1] in {"messages", "files"}:
            target_type = "私聊" if parts[-3] == "users" else "群聊"
            return [
                C.kv("target", target_type),
                C.kv("target", QqOpenApiClient._short_id(parts[-2])),
            ]
        return [C.kv("path", path)]

    @staticmethod
    def _short_id(value: object, head: int = 8, tail: int = 6) -> str:
        """缩短开放平台长 ID，保留首尾方便排查。"""

        text = str(value or "").strip()
        if not text:
            return "-"
        if len(text) <= head + tail + 3:
            return text
        return f"{text[:head]}...{text[-tail:]}"


def _positive_int(value: object, default: int, *, allow_zero: bool = False) -> int:
    """把网关返回的数值字段安全转成正整数。"""

    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < 0 or (number == 0 and not allow_zero):
        return default
    return number


class QqOpenApiError(RuntimeError):
    """QQ OpenAPI HTTP 层异常。"""

    def __init__(self, status_code: int, detail: str, *, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.detail = detail
        self.headers = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
        super().__init__(f"QQ 发消息失败：{status_code} {detail}")


class QqOpenApiTransportError(RuntimeError):
    """QQ OpenAPI 连接层异常；retryable 表示请求尚未建立连接。"""

    def __init__(self, detail: str, *, retryable: bool) -> None:
        self.detail = detail
        self.retryable = retryable
        super().__init__(f"QQ HTTP 请求失败：{detail}")


client = QqOpenApiClient()
