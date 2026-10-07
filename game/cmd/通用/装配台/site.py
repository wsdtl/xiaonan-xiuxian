"""匿名公开的方案编排接口；不提供任何玩家写入接口。"""
import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from game.app import current_game_services
from game.features.zhuangpei import ZhuangpeiFeatureError
from launch.paths import static_path

router = APIRouter(prefix="/assembly")
HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def assembly_page() -> HTMLResponse:
    return HTMLResponse(static_path("zhuangpei", "index.html").read_text(encoding="utf-8"), headers={
        **HEADERS, "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
        "Content-Security-Policy": "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
    })


@router.get("/data")
async def assembly_data(scope: str = "all") -> JSONResponse:
    try:
        return JSONResponse(await current_game_services().features.zhuangpei.page(scope), headers=HEADERS)
    except ZhuangpeiFeatureError as exc:
        return failure(str(exc))


@router.post("/scheme")
async def assembly_scheme(request: Request) -> JSONResponse:
    # 流式限长，也约束不带 Content-Length 的请求；只计算公开方案，不写存档。
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 32768:
            return failure("方案过长", 413)
    try:
        body = json.loads(raw)
        feature = current_game_services().features.zhuangpei
        if not isinstance(body, dict) or set(body) not in ({"code"}, {"build"}):
            return failure("请提交装配码或完整方案")
        value = feature.open_code(body["code"]) if "code" in body else feature.scheme(body["build"])
        return JSONResponse(value, headers=HEADERS)
    except (ValueError, UnicodeError) as exc:
        return failure(str(exc))


@router.get("/content")
async def assembly_content(section: str, content_id: str, grade: str = "") -> JSONResponse:
    try:
        return JSONResponse(
            current_game_services().features.zhuangpei.detail(section, content_id, grade),
            headers=HEADERS,
        )
    except ZhuangpeiFeatureError as exc:
        return failure(str(exc))


def failure(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status, headers=HEADERS)
