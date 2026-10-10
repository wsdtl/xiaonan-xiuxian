'''就地交易的只读货架。

页面只做一件事：把货架摆出来，拼出要发的「购买」命令原文。
**卖什么、买不买得起不在这里判**：核心说什么页面就显示什么。
能不能读某个人的数据，由全局的「网页资源」开关说话。
'''

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from game.app import current_game_services
from launch.paths import static_path

router = APIRouter(prefix='/jiaoyi')
HEADERS = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
CATEGORIES = ('真意', '气机')


@router.get('', response_class=HTMLResponse, include_in_schema=False)
async def jiaoyi_page() -> HTMLResponse:
    return HTMLResponse(
        static_path('jiaoyi', 'index.html').read_text(encoding='utf-8'),
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
async def jiaoyi_data(scope: str = '', category: str = '真意', page: int = 1) -> JSONResponse:
    services = current_game_services()
    scopes = await services.features.wangye.scopes()
    if not scopes:
        return JSONResponse({'scopes': [], 'ui': {}, 'overview': None, 'page': None, 'categories': [], 'notice': ''}, headers=HEADERS)
    picked = scope.strip() or ('user:' + scopes[0].user_id)
    user_id = picked.removeprefix('user:')
    if user_id not in {item.user_id for item in scopes}:
        return failure('这个人没有公开网页资源')
    feature = services.features.jiaoyi
    # 逐键字面读：判据要看得见谁在读这份文案（两层结构，取「页面」那一节）。
    ui = {
        '标题': feature.copy('页面', '标题'),
        '说明': feature.copy('页面', '说明'),
        '挑人': feature.copy('页面', '挑人'),
        '没人公开': feature.copy('页面', '没人公开'),
        '货架': feature.copy('页面', '货架'),
        '类别': feature.copy('页面', '类别'),
        '页码': feature.copy('页面', '页码'),
        '上一页': feature.copy('页面', '上一页'),
        '下一页': feature.copy('页面', '下一页'),
        '空': feature.copy('页面', '空'),
        '命令': feature.copy('页面', '命令'),
    }
    chosen = category if category in CATEGORIES else CATEGORIES[0]
    body: dict[str, object] = {
        'scopes': [{'id': 'user:' + item.user_id, 'name': item.name} for item in scopes],
        'scope': 'user:' + user_id,
        'ui': ui,
        'categories': list(CATEGORIES),
        'category': chosen,
        'overview': None,
        'page': None,
        'notice': '',
    }
    try:
        body['overview'] = _plain(await feature.overview(user_id))
        body['page'] = _plain(await feature.page(user_id, chosen, max(1, int(page))))
    except Exception as exc:
        body['notice'] = str(exc)
    return JSONResponse(body, headers=HEADERS)


def failure(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({'error': message}, status_code=status, headers=HEADERS)


__all__ = ['router']
