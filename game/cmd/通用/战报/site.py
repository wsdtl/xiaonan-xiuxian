"""战报页面与它的五份数据接口。

页面按「分享地址」设计（见 `static/说明.md`）：页面本身住在 `/battle/<战报编号>`，
数据从**同前缀**取。装配的五个口与页面里 `loadEndpoint` 拼的路径一一对应：

    /battle/<编号>                          页面（HTML）
    /battle/<编号>/data                     战报头（概览、演员表、花名册、片段列表）
    /battle/<编号>/segments/<序>             一个片段的全部内容
    /battle/<编号>/segments/<序>/events      一个片段的全部事件
    /battle/<编号>/segments/<序>/participants/<快照>
    /battle/<编号>/segments/<序>/transitions/<序>

数据从**存档战报现算**（`宗门战` 记录里的 `战报`），展示包不进存档：一次十五人对
十五人的仗，展示包比战报还大，而它每一步都能从战报算出来。算好的按编号留最近几份
（见 `Bank`），编号对不上就回 404，不拿空壳糊页面。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from game.app import current_game_services
from launch.paths import static_path

router = APIRouter(prefix="/battle")
INDEX_HTML = static_path("battle-report", "index.html")

#: 战报页面是公开只读的分享页：脚本与样式只许来自本站，不许外链、不许内联。
PAGE_CSP = (
    "default-src 'self'; img-src 'self' data:; "
    "style-src 'self'; script-src 'self'; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)


def _page_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Content-Security-Policy": PAGE_CSP,
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
    }


def _data_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }


@router.get("/{report_id}", response_class=HTMLResponse, include_in_schema=False)
async def battle_report_page(report_id: str) -> HTMLResponse:
    return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"), headers=_page_headers())


@router.get("/{report_id}/data", response_class=JSONResponse)
async def battle_report_data(report_id: str) -> JSONResponse:
    payload = await current_game_services().features.zhanbao.main(report_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="没有这份战报")
    return JSONResponse(payload, headers=_data_headers())


@router.get("/{report_id}/segments/{index}", response_class=JSONResponse)
async def battle_report_segment(report_id: str, index: int) -> JSONResponse:
    payload = await current_game_services().features.zhanbao.segment(report_id, index)
    if payload is None:
        raise HTTPException(status_code=404, detail="没有这个片段")
    return JSONResponse(payload, headers=_data_headers())


@router.get("/{report_id}/segments/{index}/events", response_class=JSONResponse)
async def battle_report_events(report_id: str, index: int) -> JSONResponse:
    payload = await current_game_services().features.zhanbao.events(report_id, index)
    if payload is None:
        raise HTTPException(status_code=404, detail="没有这个片段的事件")
    return JSONResponse(payload, headers=_data_headers())


@router.get(
    "/{report_id}/segments/{index}/participants/{snapshot}", response_class=JSONResponse
)
async def battle_report_participants(
    report_id: str, index: int, snapshot: str
) -> JSONResponse:
    payload = await current_game_services().features.zhanbao.participants(
        report_id, index, snapshot
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="没有这一侧的参战者状态")
    return JSONResponse(payload, headers=_data_headers())


@router.get(
    "/{report_id}/segments/{index}/transitions/{sequence}", response_class=JSONResponse
)
async def battle_report_transition(
    report_id: str, index: int, sequence: int
) -> JSONResponse:
    payload = await current_game_services().features.zhanbao.transition(
        report_id, index, sequence
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="没有这次行动的前后状态")
    return JSONResponse(payload, headers=_data_headers())


__all__ = ["router"]
