'''裂天原补天的只读看板。

页面**只负责挑**：节点与候选丹都由核心算，页面把结论摆整齐、把要发的命令原文渲染出来。
能不能读某个人的数据，由全局的「网页资源」开关说话——没开的人在这里读不到（连名字都不列）。
'''

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from game.app import current_game_services
from game.features.butian import ButianError
from launch.paths import static_path

from ...site import PAGE_CSP, PAGE_HEADERS, failure

router = APIRouter(prefix='/butian')


@router.get('', response_class=HTMLResponse, include_in_schema=False)
async def butian_page() -> HTMLResponse:
    return HTMLResponse(
        static_path('butian', 'index.html').read_text(encoding='utf-8'),
        headers={
            **PAGE_HEADERS,
            'Referrer-Policy': 'no-referrer',
            'X-Frame-Options': 'DENY',
            "Content-Security-Policy": PAGE_CSP,
        },
    )


@router.get('/data')
async def butian_data(scope: str = '') -> JSONResponse:
    services = current_game_services()
    try:
        wangye = services.features.wangye
        scopes = await wangye.scopes()
        if not scopes:
            return JSONResponse(
                {'scopes': [], 'scope': '', 'ui': {}, 'targets': [], 'candidates': [], 'medicine_id': ''},
                headers=PAGE_HEADERS,
            )
        picked = scope.strip() or ('user:' + scopes[0].user_id)
        user_id = picked.removeprefix('user:')
        if user_id not in {item.user_id for item in scopes}:
            return failure('这个人没有公开网页资源')
        value = await services.features.butian.page(user_id)
        value['scopes'] = [{'id': 'user:' + item.user_id, 'name': item.name} for item in scopes]
        value['scope'] = picked
        return JSONResponse(value, headers=PAGE_HEADERS)
    except ButianError as exc:
        return failure(str(exc))


__all__ = ['router']
