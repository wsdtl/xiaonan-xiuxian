'''万珍殿的只读捐入台。

页面只做一件事：把「你有的成品」摆出来，按分类拼出要发的命令原文。
**门槛与规则不重推**：万珍殿读口与捐入都是核心的事，核心说什么页面就显示什么。
能不能读某个人的数据，由全局的「网页资源」开关说话。
'''

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from game.app import current_game_services
from launch.paths import static_path

router = APIRouter(prefix='/wanzhen')
HEADERS = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
#: 五类成品与各自的子类（与「捐入万珍殿」命令认的写法一一对应）。
CATEGORIES = (
    ('丹药', ('恢复丹', '战丹', '突破丹', '特殊丹')),
    ('真意', ('真意',)),
    ('气机', ('气机',)),
    ('器律', ('灵器器律', '法器器律', '法宝器律', '后天灵宝器律')),
    ('阵法', ('黄品阵法', '玄品阵法', '地品阵法', '天品阵法', '圣品阵法')),
)
#: 按这些实体类别依次试取名字（编号相同就认第一个命中的）。
SECTIONS = ('丹药', '功法', '真意', '气机', '器律', '阵法')


@router.get('', response_class=HTMLResponse, include_in_schema=False)
async def wanzhen_page() -> HTMLResponse:
    return HTMLResponse(
        static_path('wanzhen', 'index.html').read_text(encoding='utf-8'),
        headers={
            **HEADERS,
            'Referrer-Policy': 'no-referrer',
            'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        },
    )


async def _entries(services, user_id: str) -> list[dict[str, object]]:
    """把自己有的成品摊平；名字按实体类别现取，取不到就用编号顶着。"""

    snapshot = await services.core.asset.snapshot(user_id)
    out: list[dict[str, object]] = []
    for entry in snapshot.entries:
        content_id = str(getattr(entry, 'content_id', ''))
        name = content_id
        for section in SECTIONS:
            try:
                raw = services.core.data.entity(section, content_id)
            except Exception:
                continue
            name = str(raw.get('名称') or content_id)
            break
        # 阵法条目的身份是「阵法编号:品级:灵宝编号」这个状态键，不是阵法编号——
        # 捐入命令要的是整串键，而灵宝决定了加成方向，两样都得交给页面。
        key = str(getattr(entry, 'instance_key', ''))
        treasure_id = key.split(':')[2] if key.count(':') >= 2 else ''
        treasure = '' if not treasure_id or treasure_id == '无灵宝' else treasure_id
        treasure_name = ''
        treasure_effect = ''
        if treasure:
            try:
                raw_treasure = dict(services.core.data.entity('先天灵宝', treasure))
            except Exception:
                raw_treasure = {}
            treasure_name = str(raw_treasure.get('名称') or treasure)
            effect = raw_treasure.get('规则介入') or {}
            if hasattr(effect, 'get'):
                ability = str(effect.get('能力') or '')
                scale = ''
                for key_name, suffix in (('比例', '%'), ('数量', ''), ('次数', ''), ('进度', '')):
                    if effect.get(key_name) is not None:
                        value = effect[key_name]
                        scale = str(int(round(float(value) * 100))) + suffix if suffix else str(value)
                        break
                treasure_effect = (ability + ' ' + scale).strip()
        out.append(
            {
                'subcategory': str(getattr(entry, 'subcategory', '')),
                'id': content_id,
                'key': key,
                'grade': str(getattr(entry, 'grade_id', '')),
                'quantity': int(getattr(entry, 'quantity', 0) or 0),
                'name': name,
                'treasure': treasure,
                'treasure_name': treasure_name,
                'treasure_effect': treasure_effect,
            }
        )
    return out


@router.get('/data')
async def wanzhen_data(scope: str = '') -> JSONResponse:
    services = current_game_services()
    scopes = await services.features.wangye.scopes()
    if not scopes:
        return JSONResponse({'scopes': [], 'ui': {}, 'categories': [], 'items': [], 'vault': '', 'notice': ''}, headers=HEADERS)
    picked = scope.strip() or ('user:' + scopes[0].user_id)
    user_id = picked.removeprefix('user:')
    if user_id not in {item.user_id for item in scopes}:
        return failure('这个人没有公开网页资源')
    feature = services.features.zongmen_wanzhen
    # 文案是 dataclass（WanzhenCopy），正文在 .text 里——不是 dict.get。
    raw = feature.copy()
    text = getattr(raw, 'text', raw)
    # 这份文案的包装只认平键：嵌套对象会被包成字符串（实测过），所以页面文案摊平成「页面X」。
    # 逐键字面取：动态拼键名会让「谁读了这个文案」查不出来，判据就认不出消费者。
    pick = (lambda key: str(text.get(key) or '')) if hasattr(text, 'get') else (lambda key: '')
    ui = {
        '标题': pick('页面标题'),
        '说明': pick('页面说明'),
        '挑人': pick('页面挑人'),
        '没人公开': pick('页面没人公开'),
        '分类': pick('页面分类'),
        '成品': pick('页面成品'),
        '数量': pick('页面数量'),
        '命令': pick('页面命令'),
        '没有成品': pick('页面没有成品'),
        '灵宝': pick('页面灵宝'),
        '无灵宝': pick('页面无灵宝'),
    }
    everything = await _entries(services, user_id)
    items: list[dict[str, object]] = []
    for name, subs in CATEGORIES:
        for row in everything:
            if str(row['subcategory']) in subs:
                items.append({'category': name, **row})
    value: dict[str, object] = {
        'scopes': [{'id': 'user:' + item.user_id, 'name': item.name} for item in scopes],
        'scope': 'user:' + user_id,
        'ui': ui,
        'categories': [name for name, _subs in CATEGORIES],
        'items': items,
        'vault': '',
        'notice': '',
    }
    try:
        listed = await feature.page(user_id, '全部', 1)
        value['vault'] = '第 %s 页 / 共 %s 页，条目 %s 件' % (
            getattr(listed, 'page', 1), getattr(listed, 'page_count', 1), getattr(listed, 'total', 0),
        )
    except Exception as exc:
        value['notice'] = str(exc)
    return JSONResponse(value, headers=HEADERS)


def failure(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({'error': message}, status_code=status, headers=HEADERS)


__all__ = ['router']
