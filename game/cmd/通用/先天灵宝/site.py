'''灵宝谱的只读挑选台。

页面只做一件事：把你灵宝谱里的先天灵宝摆出来，拼出要发的命令原文。
**能不能执掌不在这里判**：核心说什么页面就显示什么。
能不能读某个人的数据，由全局的「网页资源」开关说话。
'''

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from game.app import current_game_services
from launch.paths import static_path

router = APIRouter(prefix='/lingbao')
HEADERS = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}


@router.get('', response_class=HTMLResponse, include_in_schema=False)
async def lingbao_page() -> HTMLResponse:
    return HTMLResponse(
        static_path('lingbao', 'index.html').read_text(encoding='utf-8'),
        headers={
            **HEADERS,
            'Referrer-Policy': 'no-referrer',
            'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        },
    )


def _plain(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, 'items'):
        return {str(key): _plain(raw) for key, raw in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    fields = getattr(value, '__dataclass_fields__', None)
    if fields:
        return {name: _plain(getattr(value, name)) for name in fields}
    return str(value)


@router.get('/data')
async def lingbao_data(scope: str = '') -> JSONResponse:
    services = current_game_services()
    scopes = await services.features.wangye.scopes()
    if not scopes:
        return JSONResponse({'scopes': [], 'ui': {}, 'active': None, 'owned': []}, headers=HEADERS)
    picked = scope.strip() or ('user:' + scopes[0].user_id)
    user_id = picked.removeprefix('user:')
    if user_id not in {item.user_id for item in scopes}:
        return failure('这个人没有公开网页资源')
    feature = services.features.xiantian_lingbao
    # 走特性公开的 copy(key)，并且**逐键字面写**：判据要看见谁在读这份文案。
    ui = {
        '标题': feature.copy('页面标题'),
        '说明': feature.copy('页面说明'),
        '挑人': feature.copy('页面挑人'),
        '没人公开': feature.copy('页面没人公开'),
        '当前': feature.copy('页面当前'),
        '没有当前': feature.copy('页面没有当前'),
        '自备': feature.copy('页面自备'),
        '没有自备': feature.copy('页面没有自备'),
        '命令': feature.copy('页面命令'),
    }
    try:
        view = await feature.inspect(user_id, page=1)
    except Exception as exc:
        return JSONResponse(
            {'scopes': [{'id': 'user:' + item.user_id, 'name': item.name} for item in scopes],
             'scope': 'user:' + user_id, 'ui': ui, 'active': None, 'owned': [], 'notice': str(exc)},
            headers=HEADERS,
        )
    return JSONResponse(
        {
            'scopes': [{'id': 'user:' + item.user_id, 'name': item.name} for item in scopes],
            'scope': 'user:' + user_id,
            'ui': ui,
            'active': _plain(view.active),
            'owned': [_plain(item) for item in view.owned],
            'page': view.page,
            'page_count': view.page_count,
            'total': view.total_count,
            'notice': '',
        },
        headers=HEADERS,
    )


def failure(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({'error': message}, status_code=status, headers=HEADERS)


__all__ = ['router']
