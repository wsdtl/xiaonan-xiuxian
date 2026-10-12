"""公开只读的晓楠修仙界地图页面与数据接口。"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from game.app import current_game_services
from launch.paths import static_path

from ...presentation import PAGE_CSP_WITH_IMAGES, PAGE_HEADERS

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


def _page_headers() -> dict[str, str]:
    """这一页的响应头：共用基础头 + 本页单独的 CSP 与来源限制。"""

    return {
        **PAGE_HEADERS,
        "Content-Security-Policy": PAGE_CSP_WITH_IMAGES,
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "SAMEORIGIN",
    }




__all__ = ["router"]
