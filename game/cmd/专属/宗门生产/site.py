'''宗门灵田的只读选地形台。

页面只做一件事：把这座设施可选的地形摆出来，拼出要发的命令原文。
**能不能选不在这里判**：核心说什么页面就显示什么。
能不能读某个人的数据，由全局的「网页资源」开关说话。
'''

from collections.abc import Mapping

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from game.app import current_game_services
from launch.paths import static_path

from ...presentation import PAGE_CSP, PAGE_HEADERS

router = APIRouter(prefix='/lingtian')
#: 这座设施的常用命令（与命令组认的写法一致，页面直接把它们摆出来）。
USUAL = ('灵田', '灵田 开启', '灵田 收取', '灵田 清地形')


@router.get('', response_class=HTMLResponse, include_in_schema=False)
async def lingtian_page() -> HTMLResponse:
    return HTMLResponse(
        static_path('lingtian', 'index.html').read_text(encoding='utf-8'),
        headers={
            **PAGE_HEADERS,
            'Referrer-Policy': 'no-referrer',
            'X-Frame-Options': 'DENY',
            'Content-Security-Policy': PAGE_CSP,
        },
    )


@router.get('/data')
async def lingtian_data(scope: str = '') -> JSONResponse:
    services = current_game_services()
    scopes = await services.features.wangye.scopes()
    if not scopes:
        return JSONResponse({'scopes': [], 'ui': {}, 'terrains': [], 'terrain': '', 'notice': '', 'usual': list(USUAL)}, headers=PAGE_HEADERS)
    picked = scope.strip() or ('user:' + scopes[0].user_id)
    user_id = picked.removeprefix('user:')
    if user_id not in {item.user_id for item in scopes}:
        return failure('这个人没有公开网页资源')
    feature = services.features.zongmen_shengchan
    # 逐键字面读：判据要看得见谁在读这份文案（这一组是两层结构，取「灵田」那一层）。
    groups = feature.copy()
    group = groups.get('灵田', {}) if isinstance(groups, Mapping) else {}
    pick = (lambda key: str(group.get(key) or '')) if isinstance(group, Mapping) else (lambda key: '')
    ui = {
        '标题': pick('页面标题'),
        '说明': pick('页面说明'),
        '挑人': pick('页面挑人'),
        '没人公开': pick('页面没人公开'),
        '地形': pick('页面地形'),
        '当前地形': pick('页面当前地形'),
        '未选': pick('页面未选'),
        '命令': pick('页面命令'),
        '常用': pick('页面常用'),
    }
    value: dict[str, object] = {
        'scopes': [{'id': 'user:' + item.user_id, 'name': item.name} for item in scopes],
        'scope': 'user:' + user_id,
        'ui': ui,
        'terrains': list(feature.terrain_options('灵田')),
        'terrain': '',
        'notice': '',
        'usual': list(USUAL),
    }
    try:
        view = await feature.view('灵田', user_id)
        value['terrain'] = str(getattr(view, 'terrain', '') or '')
        value['started'] = bool(getattr(view, 'started', False))
    except Exception as exc:
        value['notice'] = str(exc)
    return JSONResponse(value, headers=PAGE_HEADERS)


def failure(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({'error': message}, status_code=status, headers=PAGE_HEADERS)


__all__ = ['router']
