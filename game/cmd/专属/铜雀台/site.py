'''铜雀台看板。

页面只做两件事：把核心的预览摆出来，拼出要发的命令原文。
**规则不在这里判**：核心说什么页面就显示什么。
能不能读某个人的数据，由全局的「网页资源」开关说话。
'''

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from game.app import current_game_services
from launch.paths import static_path

from ...presentation import PAGE_CSP, PAGE_HEADERS, to_jsonable

from ...presentation import to_jsonable

router = APIRouter(prefix='/tongquetai')


@router.get('', response_class=HTMLResponse, include_in_schema=False)
async def tongquetai_page() -> HTMLResponse:
    return HTMLResponse(
        static_path('tongquetai', 'index.html').read_text(encoding='utf-8'),
        headers={
            **PAGE_HEADERS,
            'Referrer-Policy': 'no-referrer',
            'X-Frame-Options': 'DENY',
            'Content-Security-Policy': PAGE_CSP,
        },
    )


@router.get('/data')
async def tongquetai_data(scope: str = '') -> JSONResponse:
    services = current_game_services()
    scopes = await services.features.wangye.scopes()
    if not scopes:
        return JSONResponse({'scopes': [], 'ui': {}, 'preview': None, 'notice': '', 'modes': []}, headers=PAGE_HEADERS)
    picked = scope.strip() or ('user:' + scopes[0].user_id)
    user_id = picked.removeprefix('user:')
    if user_id not in {item.user_id for item in scopes}:
        return failure('这个人没有公开网页资源')
    feature = services.features.tongquetai
    # 逐键字面读：判据要看得见谁在读这份文案（两层结构，取「页面」那一节）。
    ui = {
        '标题': feature.copy('页面', '标题'),
        '说明': feature.copy('页面', '说明'),
        '挑人': feature.copy('页面', '挑人'),
        '没人公开': feature.copy('页面', '没人公开'),
        '地点': feature.copy('页面', '地点'),
        '道侣': feature.copy('页面', '道侣'),
        '层级': feature.copy('页面', '层级'),
        '丹药': feature.copy('页面', '丹药'),
        '模式': feature.copy('页面', '模式'),
        '护契': feature.copy('页面', '护契'),
        '离契': feature.copy('页面', '离契'),
        '给': feature.copy('页面', '给'),
        '收': feature.copy('页面', '收'),
        '弃': feature.copy('页面', '弃'),
        '命令': feature.copy('页面', '命令'),
    }
    body: dict[str, object] = {
        'scopes': [{'id': 'user:' + item.user_id, 'name': item.name} for item in scopes],
        'scope': 'user:' + user_id,
        'ui': ui,
        'preview': None,
        'notice': '',
        'modes': ['护契', '离契'],
    }
    try:
        body['preview'] = to_jsonable(await feature.preview(user_id))
    except Exception as exc:
        body['notice'] = str(exc)
    return JSONResponse(body, headers=PAGE_HEADERS)


def failure(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({'error': message}, status_code=status, headers=PAGE_HEADERS)


__all__ = ['router']
