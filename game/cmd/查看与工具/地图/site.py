"""公开只读的晓楠修仙界地图页面与数据接口。"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from game.app import current_game_services
from launch.paths import static_path

from ...site import PAGE_HEADERS

#: 地图页要把图片画在 <canvas> 或内联 data: 图片上，所以在本页单独声明内容安全策略。
PAGE_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)


def _page_headers() -> dict[str, str]:
    """这一页的响应头：共用基础头 + 本页策略与来源限制。

    头名显式写在本页——下发 HTML 的模块自己声明内容安全策略。
    """

    return {
        **PAGE_HEADERS,
        "Content-Security-Policy": PAGE_CSP,
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "SAMEORIGIN",
    }

router = APIRouter(prefix="/world-map")
INDEX_HTML = static_path("world-map", "index.html")


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def world_map_page() -> HTMLResponse:
    return HTMLResponse(
        INDEX_HTML.read_text(encoding="utf-8"),
        headers=_page_headers(),
    )


@router.get("/data", response_class=JSONResponse)
async def world_map_data() -> JSONResponse:
    snapshot = current_game_services().features.ditu.snapshot()
    return JSONResponse(asdict(snapshot), headers=PAGE_HEADERS)


__all__ = ["router"]
