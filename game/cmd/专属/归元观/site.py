'''归元观看板。

页面只做两件事：把核心的预览摆出来，拼出要发的命令原文。
**规则不在这里判**：核心说什么页面就显示什么。
能不能读某个人的数据，由全局的「网页资源」开关说话。
'''

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from game.app import current_game_services
from launch.paths import static_path

from ...site import PAGE_CSP, PAGE_HEADERS, failure


router = APIRouter(prefix='/guiyuan')


def _preview_view(value: object) -> dict[str, object]:
    '''把归元观的预览投影成页面要的**中文形状**。

    标签就是这份数据里的「道侣／丹药／构筑」；构筑的条数与聊天侧同一套写法
    （聊天侧印「{类别} · 当前承载 {数量} 项」）。页面只照印，不自己翻英文键。
    '''

    return {
        '地点': str(value.location_name),
        '道侣': str(value.companion_name),
        '丹药': str(value.medicine_name),
        '丹药齐备': bool(value.has_medicine),
        '构筑': [
            {'类别': str(category), '数量': int(count)}
            for category, count in value.counts
        ],
    }


@router.get('', response_class=HTMLResponse, include_in_schema=False)
async def guiyuan_page() -> HTMLResponse:
    return HTMLResponse(
        static_path('guiyuan', 'index.html').read_text(encoding='utf-8'),
        headers={
            **PAGE_HEADERS,
            'Referrer-Policy': 'no-referrer',
            'X-Frame-Options': 'DENY',
            'Content-Security-Policy': PAGE_CSP,
        },
    )


@router.get('/data')
async def guiyuan_data(scope: str = '') -> JSONResponse:
    services = current_game_services()
    scopes = await services.features.wangye.scopes()
    if not scopes:
        return JSONResponse({'scopes': [], 'ui': {}, 'preview': None, 'notice': '', 'categories': []}, headers=PAGE_HEADERS)
    picked = scope.strip() or ('user:' + scopes[0].user_id)
    user_id = picked.removeprefix('user:')
    if user_id not in {item.user_id for item in scopes}:
        return failure('这个人没有公开网页资源')
    feature = services.features.guiyuan
    # 逐键字面读：判据要看得见谁在读这份文案（这一份是两层结构，取「页面」那一节）。
    ui = {
        '标题': feature.copy('页面', '标题'),
        '说明': feature.copy('页面', '说明'),
        '挑人': feature.copy('页面', '挑人'),
        '没人公开': feature.copy('页面', '没人公开'),
        '地点': feature.copy('页面', '地点'),
        '道侣': feature.copy('页面', '道侣'),
        '丹药': feature.copy('页面', '丹药'),
        '构筑': feature.copy('页面', '构筑'),
        '空': feature.copy('页面', '空'),
        '命令': feature.copy('页面', '命令'),
        '类别': feature.copy('页面', '类别'),
        # 「有丹／无丹」两句在预览那一节：页面要照印后端的话，不自己判。
        '有丹': feature.copy('预览', '有丹'),
        '无丹': feature.copy('预览', '无丹'),
    }
    body: dict[str, object] = {
        'scopes': [{'id': 'user:' + item.user_id, 'name': item.name} for item in scopes],
        'scope': 'user:' + user_id,
        'ui': ui,
        'preview': None,
        'notice': '',
        'categories': ['功法', '真意', '气机'],
    }
    try:
        body['preview'] = _preview_view(await feature.preview(user_id))
    except Exception as exc:
        body['notice'] = str(exc)
    return JSONResponse(body, headers=PAGE_HEADERS)


__all__ = ['router']
