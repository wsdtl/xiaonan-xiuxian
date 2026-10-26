'''灵宝谱的只读挑选台。

页面只做一件事：把你灵宝谱里的先天灵宝摆出来，拼出要发的命令原文。
**能不能执掌不在这里判**：核心说什么页面就显示什么。
能不能读某个人的数据，由全局的「网页资源」开关说话。
'''

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from game.app import current_game_services
from launch.paths import static_path

from ...site import PAGE_CSP, PAGE_HEADERS, failure


router = APIRouter(prefix='/lingbao')


@router.get('', response_class=HTMLResponse, include_in_schema=False)
async def lingbao_page() -> HTMLResponse:
    return HTMLResponse(
        static_path('tool', 'lingbao', 'index.html').read_text(encoding='utf-8'),
        headers={
            **PAGE_HEADERS,
            'Referrer-Policy': 'no-referrer',
            'X-Frame-Options': 'DENY',
            'Content-Security-Policy': PAGE_CSP,
        },
    )


def _treasure_view(item: object) -> dict[str, str]:
    '''一件灵宝摊成页面要的中文形状；标签取自展示数据集（权柄／效果），页面不自己翻英文键。'''

    effect = getattr(item, 'effect', None)
    return {
        '编号': str(item.treasure_id),
        '名称': str(item.name),
        '权柄': str(item.authority),
        '说明': str(item.description),
        '效果': f'{effect.node}：{effect.ability}' if effect is not None else '',
        '加成方向': str(effect.node) if effect is not None else '',
    }


@router.get('/data')
async def lingbao_data(scope: str = '', page: int = 1, view: str = '') -> JSONResponse:
    services = current_game_services()
    scopes = await services.features.wangye.scopes()
    if not scopes:
        return JSONResponse({'scopes': [], 'ui': {}, 'active': None, 'owned': []}, headers=PAGE_HEADERS)
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
        # 全谱那一页的词数据里早有（谱标题／谱行权柄／谱行加成）：照印，不自己造。
        # 带占位符的两句（谱说明的 {总数}、页码的 {当前页}/{总页数}）要等取到数再排版，见下面。
        '谱标题': feature.copy('谱标题'),
        '谱行权柄': feature.copy('谱行权柄'),
        '谱行加成': feature.copy('谱行加成'),
        '权柄': feature.copy('权柄'),
        '效果': feature.copy('效果'),
    }
    mode = 'all' if view.strip() == 'all' else 'owned'
    try:
        got = (
            await feature.catalog(max(1, int(page)))
            if mode == 'all'
            else await feature.inspect(user_id, page=max(1, int(page)))
        )
    except Exception as exc:
        return JSONResponse(
            {'scopes': [{'id': 'user:' + item.user_id, 'name': item.name} for item in scopes],
             'scope': 'user:' + user_id, 'ui': ui, 'active': None, 'owned': [], 'notice': str(exc)},
            headers=PAGE_HEADERS,
        )
    # 两句带占位符的文案都用数据里的模板填（与聊天侧同一套写法），页面不自己拼。
    page_text = feature.copy('页码', {'当前页': got.page, '总页数': got.page_count})
    catalog_text = feature.copy('谱说明', {'总数': got.total_count})
    return JSONResponse(
        {
            'scopes': [{'id': 'user:' + item.user_id, 'name': item.name} for item in scopes],
            'scope': 'user:' + user_id,
            'ui': ui,
            'mode': mode,
            'active': _treasure_view(got.active) if got.active else None,
            'owned': [_treasure_view(item) for item in got.owned],
            'page': got.page,
            'page_count': got.page_count,
            'total': got.total_count,
            'page_text': page_text,
            'catalog_text': catalog_text,
            'notice': '',
        },
        headers=PAGE_HEADERS,
    )


__all__ = ['router']
