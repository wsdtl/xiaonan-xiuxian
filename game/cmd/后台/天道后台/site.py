"""受密码保护的天道后台 HTTP 接口。"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from launch.paths import static_path

from .console import CONSOLE_SENDER_NAME, SESSION_COOKIE_NAME, service
from .models import ConsoleSession
from .presentation import record_payload

router = APIRouter(prefix="/game-console")
INDEX_HTML = static_path("game-console", "index.html")

#: 天道后台页面的内容安全策略。
#:
#: 舆图页面一直有自限策略，后台页面此前**一条都没有**——后台是能下发命令的入口，
#: 更该锁住脚本来源。这里放开的三处都是页面真实需要的：
#: `cdn.jsdelivr.net` 供 KaTeX 的样式、脚本与字体（两个文件都带 `integrity`，
#: 改过内容就加载不出来）；`img-src` 放开 http/https，因为消息图片允许外链
#: （本地图片已经由消息媒体目录物化成 `/game-console/media/`）。
#: 数学公式的行内样式走的是 CSSOM，不需要 `style-src 'unsafe-inline'`。
CONSOLE_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net; "
    "style-src 'self' https://cdn.jsdelivr.net; "
    "font-src 'self' data: https://cdn.jsdelivr.net; "
    "img-src 'self' data: http: https:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


class LoginRequest(BaseModel):
    username: str
    password: str


class CommandRequest(BaseModel):
    command: str


class ActionRequest(BaseModel):
    flow_id: int
    action_id: str


def current_session(request: Request) -> ConsoleSession:
    session = service.auth.require(request.cookies.get(SESSION_COOKIE_NAME, ""))
    if session is None:
        raise HTTPException(status_code=401, detail="天道后台尚未登录或会话已过期")
    return session


def write_session(
    request: Request,
    session: Annotated[ConsoleSession, Depends(current_session)],
    x_csrf_token: Annotated[str, Header()] = "",
) -> ConsoleSession:
    if not service.auth.verify_csrf(session, x_csrf_token):
        raise HTTPException(status_code=403, detail="天道后台操作校验失败")
    origin = str(request.headers.get("origin") or "").rstrip("/")
    expected = str(request.base_url).rstrip("/")
    if origin and origin != expected:
        raise HTTPException(status_code=403, detail="天道后台拒绝跨站操作")
    return session


@router.get("", response_class=HTMLResponse)
async def console_page() -> HTMLResponse:
    if not service.auth.configured:
        return HTMLResponse(
            "<h1>天道后台尚未启用</h1><p>请在 .env 中设置 WEB_CONSOLE_PASSWORD。</p>",
            status_code=503,
        )
    return HTMLResponse(
        INDEX_HTML.read_text(encoding="utf-8"),
        headers=_no_store_headers(),
    )


@router.post("/login")
async def login(
    payload: LoginRequest, request: Request, response: Response
) -> dict[str, object]:
    if not service.auth.configured:
        raise HTTPException(status_code=503, detail="天道后台尚未配置密码")
    source = request.client.host if request.client is not None else "unknown"
    if service.auth.is_rate_limited(source):
        raise HTTPException(status_code=429, detail="登录失败次数过多，请稍后再试")
    session = service.auth.login(payload.username, payload.password, source=source)
    if session is None:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session.session_id,
        max_age=12 * 60 * 60,
        httponly=True,
        secure=request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto") == "https",
        samesite="strict",
        path="/game-console",
    )
    return _session_payload(session)


@router.get("/api/session")
async def session_info(
    session: Annotated[ConsoleSession, Depends(current_session)],
) -> dict[str, object]:
    return _session_payload(session)


@router.post("/api/logout")
async def logout(
    request: Request,
    response: Response,
    session: Annotated[ConsoleSession, Depends(write_session)],
) -> dict[str, bool]:
    service.auth.logout(session.session_id)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/game-console")
    return {"ok": True}


@router.get("/api/messages")
async def recent_messages(
    _: Annotated[ConsoleSession, Depends(current_session)],
    limit: int = 50,
    before_id: int | None = None,
) -> dict[str, object]:
    records = service.recent(limit=limit, before_id=before_id)
    return {
        "records": [record_payload(record) for record in records],
        "has_more": len(records) >= max(1, min(limit, 50)),
    }


@router.get("/api/stream")
async def message_stream(
    request: Request,
    _: Annotated[ConsoleSession, Depends(current_session)],
    after_id: int = 0,
) -> StreamingResponse:
    header_cursor = str(request.headers.get("last-event-id") or "").strip()
    if header_cursor.isdigit():
        after_id = max(after_id, int(header_cursor))
    queue = await service.subscribe(after_id=max(0, after_id))

    async def events():
        try:
            yield "retry: 2000\n\n"
            while not await request.is_disconnected():
                try:
                    record = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                try:
                    if record is None:
                        break
                    payload = json.dumps(
                        record_payload(record),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    yield f"id: {record.flow_id}\ndata: {payload}\n\n"
                finally:
                    queue.task_done()
        finally:
            await service.unsubscribe(queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Content-Encoding": "identity",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/command")
async def dispatch_command(
    payload: CommandRequest,
    _: Annotated[ConsoleSession, Depends(write_session)],
) -> dict[str, object]:
    try:
        result = await service.dispatch(payload.command)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "matched": result.matched,
        "matched_count": result.matched_count,
        "event_id": result.event.event_id,
    }


@router.post("/api/action")
async def dispatch_action(
    payload: ActionRequest,
    _: Annotated[ConsoleSession, Depends(write_session)],
) -> dict[str, object]:
    try:
        result = await service.execute_action(payload.flow_id, payload.action_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {
        "ok": True,
        "kind": result.kind,
        "value": result.value,
        "matched": result.matched,
    }


@router.get("/media/{name}")
async def console_media(
    name: str,
    _: Annotated[ConsoleSession, Depends(current_session)],
) -> FileResponse:
    path = service.media_path(name)
    if path is None:
        raise HTTPException(status_code=404, detail="消息媒体不存在或已经过期")
    return FileResponse(path, headers=_no_store_headers())


def _session_payload(session: ConsoleSession) -> dict[str, object]:
    return {
        "authenticated": True,
        "username": session.username,
        "operator_name": CONSOLE_SENDER_NAME,
        "csrf_token": session.csrf_token,
        "expires_at": session.expires_at,
    }


def _no_store_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Content-Security-Policy": CONSOLE_CSP,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "same-origin",
        "X-Frame-Options": "DENY",
    }


__all__ = ["router"]
