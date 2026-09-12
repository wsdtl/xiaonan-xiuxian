"""QQ webhook HTTP 入口。

本文件只负责 FastAPI 路由层：读取 JSON、处理开放平台地址验证、
把普通事件交给 handler。真正的命令调度不在 HTTP 入口里完成。
"""

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from launch.config import config
from launch.log import C, logger

from .handler import QqEventHandler
from .signature import SIGNATURE_HEADER, TIMESTAMP_HEADER, verify_event_signature

QQ_EVENT_BASE_ROUTE = config.get("QQ_EVENT_PATH", "/qq/events") or "/qq/events"
QQ_EVENT_ROUTE = QQ_EVENT_BASE_ROUTE.rstrip("/") or "/qq/events"
QQ_EVENT_MAX_BODY_BYTES = 1024 * 1024
router = APIRouter()


@router.post(QQ_EVENT_ROUTE)
async def qq_event_endpoint(request: Request) -> dict[str, Any]:
    """接收唯一 QQ 机器人的开放平台事件回调。"""

    return await _handle_qq_event(request)


async def _handle_qq_event(request: Request) -> dict[str, Any]:
    """接收 QQ 开放平台事件回调。

    op=13 是开放平台的回调地址验证，必须同步返回签名结果。
    其他 payload 统一交给 QqEventHandler，handler 会快速 ACK 并把消息
    事件放进后台任务队列。

    这个函数必须保持很薄：HTTP 层只负责读 JSON 和分流验证请求，业务处理
    全部放到 handler，避免开放平台因为响应慢而重试。
    """

    body = await _read_request_body(request)
    payload = _read_payload(body)
    op = payload.get("op")

    if op == 13:
        try:
            response = await QqEventHandler.validation(payload)
        except ValueError as exc:
            logger.opt(colors=True).warning(
                f"{C.warn('QQ 回调验证失败')} {C.kv('reason', exc)}"
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        logger.opt(colors=True).success(
            f"{C.ok('QQ 回调验证已响应')}"
        )
        return response

    _verify_event_signature(request, config.get("QQ_BOT_SECRET", "").strip(), body)
    return await QqEventHandler.dispatch(payload=payload)


async def _read_request_body(request: Request) -> bytes:
    """按上限读取原始 JSON body，保留签名校验所需的逐字节内容。"""

    content_type = str(request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(status_code=415, detail="QQ 回调 Content-Type 必须是 application/json")

    content_length = str(request.headers.get("content-length") or "").strip()
    if content_length:
        try:
            if int(content_length) > QQ_EVENT_MAX_BODY_BYTES:
                raise HTTPException(status_code=413, detail="QQ 回调请求体过大")
        except ValueError:
            raise HTTPException(status_code=400, detail="Content-Length 无效")

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > QQ_EVENT_MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="QQ 回调请求体过大")
        chunks.append(chunk)
    return b"".join(chunks)


def _verify_event_signature(request: Request, bot_secret: str, body: bytes) -> None:
    """校验 QQ 普通事件请求签名；本地调试可通过 env 显式关闭。"""

    try:
        required = _qq_event_signature_required()
    except ValueError as exc:
        logger.opt(colors=True).error(
            C.join(
                C.fail("QQ 普通事件签名配置无效"),
                C.kv("reason", exc),
            )
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not required:
        logger.opt(colors=True).warning(f"{C.warn('QQ 普通事件签名校验已关闭，仅限本地调试')}")
        return

    try:
        verify_event_signature(
            bot_secret,
            request.headers.get(TIMESTAMP_HEADER, ""),
            body,
            request.headers.get(SIGNATURE_HEADER, ""),
        )
    except ValueError as exc:
        logger.opt(colors=True).warning(
            C.join(
                C.warn("QQ 普通事件签名校验失败"),
                C.kv("reason", exc),
            )
        )
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _qq_event_signature_required() -> bool:
    raw = str(config.get("QQ_EVENT_SIGNATURE_REQUIRED", "true") or "true").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"QQ_EVENT_SIGNATURE_REQUIRED 只能是 true/false，当前值是：{raw}")


def _read_payload(body: bytes) -> dict[str, Any]:
    """读取并校验 QQ webhook JSON。

    QQ 正常回调一定是 JSON object。非 object 直接返回 400，方便定位配置
    或代理问题；对象内部字段缺失则交给 handler 走 ACK 兼容逻辑。
    """

    try:
        payload = json.loads(body)
    except Exception as exc:
        logger.opt(colors=True, exception=exc).warning(f"{C.warn('QQ 回调 JSON 无效')}")
        raise HTTPException(status_code=400, detail="JSON 无效") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="QQ 回调内容必须是对象")
    return payload
