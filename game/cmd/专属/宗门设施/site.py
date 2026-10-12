'''演阵台的只读计算台。

页面只做两件事：把核心认得的阵法摆出来，把玩家填的三相投入交给核心算。
**不算自己的规则**：能不能炼、要多少料，全是核心的原话，页面原样转达。
能不能读某个人的数据，由全局的「网页资源」开关说话。
'''

from collections.abc import Mapping

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from game.app import current_game_services
from game.features.zongmen_sheshi import SectFacilityFeatureError
from launch.paths import static_path

from ...site import PAGE_CSP, PAGE_HEADERS, failure

router = APIRouter(prefix='/lianzhen')
GRADES = ('01', '02', '03', '04', '05')


@router.get('', response_class=HTMLResponse, include_in_schema=False)
async def lianzhen_page() -> HTMLResponse:
    return HTMLResponse(
        static_path('lianzhen', 'index.html').read_text(encoding='utf-8'),
        headers={
            **PAGE_HEADERS,
            'Referrer-Policy': 'no-referrer',
            'X-Frame-Options': 'DENY',
            'Content-Security-Policy': PAGE_CSP,
        },
    )


async def _picked(scope: str) -> tuple[str, list[dict[str, str]]]:
    services = current_game_services()
    scopes = await services.features.wangye.scopes()
    if not scopes:
        return '', []
    picked = scope.strip() or ('user:' + scopes[0].user_id)
    user_id = picked.removeprefix('user:')
    if user_id not in {item.user_id for item in scopes}:
        raise ValueError('这个人没有公开网页资源')
    return user_id, [{'id': 'user:' + item.user_id, 'name': item.name} for item in scopes]


@router.get('/data')
async def lianzhen_data(scope: str = '') -> JSONResponse:
    services = current_game_services()
    try:
        user_id, scopes = await _picked(scope)
    except ValueError as exc:
        return failure(str(exc))
    if not user_id:
        return JSONResponse(
            {'scopes': [], 'scope': '', 'ui': {}, 'grades': list(GRADES), 'formations': [], 'notice': ''},
            headers=PAGE_HEADERS,
        )
    feature = services.features.zongmen_sheshi
    # 数据服务交出来的是只读映射（MappingProxy），不是 dict——按 dict 判会恒假，文案就全空了。
    groups = feature.copy().get('演阵台', {})
    page_copy = groups.get('页面', {}) if isinstance(groups, Mapping) else {}
    pick = (lambda key: str(page_copy.get(key) or '')) if isinstance(page_copy, Mapping) else (lambda key: '')
    ui = {
        '标题': pick('标题'),
        '说明': pick('说明'),
        '挑人': pick('挑人'),
        '没人公开': pick('没人公开'),
        '阵法': pick('阵法'),
        '品级': pick('品级'),
        '三相': pick('三相'),
        '算一算': pick('算一算'),
        '命令': pick('命令'),
        '结果': pick('结果'),
    }
    value: dict[str, object] = {
        'scopes': scopes,
        'scope': 'user:' + user_id,
        'ui': ui,
        'grades': list(GRADES),
        'formations': [
            {'id': str(row_id), 'name': str(raw.get('名称') or '')}
            for row_id, raw in sorted(services.core.data.entities('阵法').items())
        ],
        'notice': '',
    }
    try:
        listed = await feature.page('炼阵', user_id, '个人纳戒')
        # 能让核心列出自己认得的阵法时，就用核心的那份；不能就退回总目。
        rows = getattr(listed, 'entries', ()) or ()
        value['formations'] = [
            {'id': str(getattr(row, 'content_id', '')), 'name': str(getattr(row, 'name', ''))}
            for row in rows
        ]
    except SectFacilityFeatureError as exc:
        # 门槛不在页面重推：核心说什么就显示什么。
        value['notice'] = str(exc)
    return JSONResponse(value, headers=PAGE_HEADERS)


@router.get('/preview')
async def lianzhen_preview(
    scope: str = '',
    identifier: str = '',
    grade: str = '',
    shoubao: int = 0,
    lingkuang: int = 0,
    lingzhi: int = 0,
) -> JSONResponse:
    services = current_game_services()
    try:
        user_id, _scopes = await _picked(scope)
    except ValueError as exc:
        return failure(str(exc))
    if not user_id:
        return failure('还没有人公开网页资源')
    try:
        value = await services.features.zongmen_sheshi.preview(
            '炼阵',
            user_id,
            '个人纳戒',
            identifier,
            grade,
            {'兽宝': int(shoubao), '灵矿': int(lingkuang), '灵植': int(lingzhi)},
        )
    except Exception as exc:
        return JSONResponse({'notice': str(exc)}, headers=PAGE_HEADERS)
    return JSONResponse({'notice': '', 'preview': _plain(value)}, headers=PAGE_HEADERS)


def _plain(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(key): _plain(raw) for key, raw in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    fields = getattr(value, '__dataclass_fields__', None)
    if fields:
        return {name: _plain(getattr(value, name)) for name in fields}
    return str(value)


__all__ = ['router']
