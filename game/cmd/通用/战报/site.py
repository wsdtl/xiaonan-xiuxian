"""战报页面与它的数据接口。

页面按「分享地址」设计（见 `static/说明.md`）：页面住在 `/battle/<战报编号>`，数据从
同前缀的 `/battle/<编号>/data` 取——**页面一条、数据一条**，用 `view` 参数说明要哪一份：

    /battle/<编号>                     页面（HTML）
    /battle/<编号>/data                首屏：概览、演员表、花名册、片段表
    /battle/<编号>/data?view=segment&index=0
    /battle/<编号>/data?view=events&index=0
    /battle/<编号>/data?view=participants&index=0&snapshot=after
    /battle/<编号>/data?view=transition&index=0&sequence=3

编号可以写成**两段纯 ASCII**（`/battle/<发起者>/<切磋编号>`）：`切磋:<发起者>:<编号>` 里的
中文与冒号会被聊天客户端自行改写（实测纯 ASCII 的 `/game-console` 才随手能开），所以分享
用两段式；`{report_id:path}` 让同一对路由同时吃两种写法，接口数量不变。

画面**每次现算**（从存档战报），服务器不缓存：这类页面多半只看一次，战报记录本身也只留
很短一段时间；缓存一旦与存档错开，玩家看到的就是上一版画面。**没有离线/预览模式**——
那是同一份数据的第二份副本，早就该删。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
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
        # 画面是实时的：不许任何一层拿旧的糊弄玩家。
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }


def identifier_of(raw: str) -> str:
    """把分享地址里的路径还原成存档战报的编号。

    两段式（`<发起者>/<切磋编号>`）拼回 `切磋:<发起者>:<编号>`；一段式原样使用（宗门战与
    旧链接都走这条）。
    """
    owner, separator, challenge_id = raw.partition("/")
    if separator and owner and challenge_id and "/" not in challenge_id:
        return f"切磋:{owner}:{challenge_id}"
    return raw


# 数据路由先注册：`{report_id:path}` 会吃掉任意段数，注册顺序决定它不会抢走页面路由。
@router.get("/{report_id:path}/data", response_class=JSONResponse)
async def battle_report_data(
    report_id: str,
    view: str = Query("header"),
    index: int = Query(0),
    snapshot: str = Query(""),
    sequence: int = Query(0),
) -> JSONResponse:
    try:
        payload = await current_game_services().features.zhanbao.view(
            identifier_of(report_id), part=view, index=index, snapshot=snapshot, sequence=sequence
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="没有这一份画面（战报不存在或还没打完）")
    return JSONResponse(payload, headers=_data_headers())


@router.get("/{report_id:path}", response_class=HTMLResponse, include_in_schema=False)
async def battle_report_page() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"), headers=_page_headers())


__all__ = ["identifier_of", "router"]
