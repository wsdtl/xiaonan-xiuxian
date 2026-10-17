'''万珍殿的只读捐入台。

页面只做一件事：把「你有的成品」摆出来，按分类拼出要发的命令原文。
**门槛与规则不重推**：万珍殿读口与捐入都是核心的事，核心说什么页面就显示什么。
能不能读某个人的数据，由全局的「网页资源」开关说话。
'''

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from game.app import current_game_services
from launch.paths import static_path

from ....site import PAGE_CSP, PAGE_HEADERS, failure

router = APIRouter(prefix='/wanzhen')
#: 五类成品与各自的子类（与「捐入万珍殿」命令认的写法一一对应）。
CATEGORIES = (
    ('丹药', ('恢复丹', '战丹', '突破丹', '特殊丹')),
    ('真意', ('真意',)),
    ('气机', ('气机',)),
    ('器律', ('灵器器律', '法器器律', '法宝器律', '后天灵宝器律')),
    ('阵法', ('黄品阵法', '玄品阵法', '地品阵法', '天品阵法', '圣品阵法')),
)


@router.get('', response_class=HTMLResponse, include_in_schema=False)
async def wanzhen_page() -> HTMLResponse:
    return HTMLResponse(
        static_path('wanzhen', 'index.html').read_text(encoding='utf-8'),
        headers={
            **PAGE_HEADERS,
            'Referrer-Policy': 'no-referrer',
            'X-Frame-Options': 'DENY',
            'Content-Security-Policy': PAGE_CSP,
        },
    )


async def _entries(services, user_id: str) -> list[dict[str, object]]:
    """把自己有的成品摊平——事实全部来自玩法，本页不碰核心服务。

    名称、品级、灵宝加成文案都由万珍殿玩法给（own_products）：页面只把数据类
    摊成 JSON 字段，不自己按类别试取名字、也不自己拼能力摘要。
    """

    rows = await services.features.zongmen_wanzhen.own_products(user_id)
    return [
        {
            'subcategory': row.subcategory,
            'id': row.content_id,
            'key': row.entry_key,
            'grade': row.grade_id,
            'quantity': row.quantity,
            'name': row.name,
            'treasure': row.treasure_id,
            'treasure_name': row.treasure_name,
            'treasure_effect': row.treasure_effect,
        }
        for row in rows
    ]


@router.get('/data')
async def wanzhen_data(scope: str = '') -> JSONResponse:
    services = current_game_services()
    scopes = await services.features.wangye.scopes()
    if not scopes:
        return JSONResponse({'scopes': [], 'ui': {}, 'categories': [], 'items': [], 'vault': '', 'notice': ''}, headers=PAGE_HEADERS)
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
        # 每类带上自己的条数：空类在页面上标成 0，不再看着像一个正常分类。
        'categories': [
            {'name': name, 'count': sum(1 for item in items if item['category'] == name)}
            for name, _subs in CATEGORIES
        ],
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
    return JSONResponse(value, headers=PAGE_HEADERS)


__all__ = ['router']
