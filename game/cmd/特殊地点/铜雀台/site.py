'''铜雀台看板。

页面只做两件事：把核心的预览摆出来，拼出要发的命令原文。
**规则不在这里判**：核心说什么页面就显示什么。
能不能读某个人的数据，由全局的「网页资源」开关说话。
'''

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from game.app import current_game_services
from launch.paths import static_path

from ...site import PAGE_CSP, PAGE_HEADERS, failure


router = APIRouter(prefix='/tongquetai')


def _outcome_view(ui: dict[str, str], outcome: object) -> dict[str, object]:
    '''一套归流方式的三个数与名字（给／收／弃都是这份数据里的词）。'''

    return {
        '给': int(outcome.offered),
        '收': int(outcome.accepted),
        '弃': int(outcome.discarded),
    }


def _preview_view(ui: dict[str, str], value: object) -> dict[str, object]:
    '''把铜雀台预览投影成页面要的**中文形状**。

    标签就是这份数据里的「道侣／层级／丹药／修为／护契／离契」，页面只照印，
    原来整份 `to_jsonable` 的英文键（companion_level／protected.offered…）页面只能自己猜。
    '''

    return {
        '地点': str(value.location_name),
        '道侣': str(value.companion_name),
        '层级': int(value.companion_level),
        '丹药': str(value.medicine_name),
        '丹药齐备': bool(value.has_medicine),
        '修为': int(value.cultivation),
        '护契': _outcome_view(ui, value.protected),
        '离契': _outcome_view(ui, value.severed),
    }


@router.get('', response_class=HTMLResponse, include_in_schema=False)
async def tongquetai_page() -> HTMLResponse:
    return HTMLResponse(
        static_path('tool', 'tongquetai', 'index.html').read_text(encoding='utf-8'),
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
        # 「有丹／没丹」两句在预览那一节：页面照印后端的话，不自己判。
        '护契可用': feature.copy('预览', '护契可用'),
        '护契不足': feature.copy('预览', '护契不足'),
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
        body['preview'] = _preview_view(ui, await feature.preview(user_id))
    except Exception as exc:
        body['notice'] = str(exc)
    return JSONResponse(body, headers=PAGE_HEADERS)


__all__ = ['router']
