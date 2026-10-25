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

from .....site import PAGE_CSP, PAGE_HEADERS, failure

router = APIRouter(prefix='/lianzhen')


@router.get('', response_class=HTMLResponse, include_in_schema=False)
async def lianzhen_page() -> HTMLResponse:
    return HTMLResponse(
        static_path('tool', 'lianzhen', 'index.html').read_text(encoding='utf-8'),
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
            {
                'scopes': [],
                'scope': '',
                'ui': {},
                # 品级候选由玩法转出：这里以前硬写编号 01–05，核心只认品级名。
                'grades': list(services.features.zongmen_sheshi.grades()),
                'formations': [],
                'notice': '',
            },
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
        'grades': list(feature.grades()),
        'formations': [
            {'id': row_id, 'name': name}
            for row_id, name in feature.formation_catalog()
        ],
        'notice': '',
    }
    try:
        listed = await feature.page('炼阵', user_id, '个人纳戒')
        # 能让核心列出自己认得的阵法时，就用核心的那份；不能就退回总目。
        rows = getattr(listed, 'entries', ()) or ()
        # 只有核心真的列得出东西才替换总目：空列表会把阵法总目整份盖掉，页面只剩一个空下拉。
        if rows:
            value['formations'] = [
                {
                    'id': str(getattr(row, 'content_id', '')),
                    'name': str(getattr(row, 'name', '')),
                    # 核心给的这一句说明（`SectFacilityEntry.detail`）：页面在选中的阵法下面照印。
                    'detail': str(getattr(row, 'detail', '')),
                }
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
    return JSONResponse(
        {'notice': '', 'preview': _formation_view(services.features.zongmen_sheshi, value)},
        headers=PAGE_HEADERS,
    )


def _formation_view(feature: object, value: object) -> dict[str, object]:
    """把玩法的演阵预览投影成页面要的**中文形状**。

    字段标签与聊天侧回执同一套（`reply.preview` 里的「阵法／品级／阵基／阵眼／节点」），
    通用文案取自展示数据集——页面只照印，不自己翻译英文键（原来是整份 JSON 甩给页面）。
    """

    groups = feature.copy().get('通用', {})
    pick = (lambda key: str(groups.get(key) or '')) if isinstance(groups, Mapping) else (lambda key: '')
    assessment = value.assessment
    formation = assessment.formation
    detection = assessment.detection
    detection_text = (
        f'{detection.field}｜{detection.relation}｜冲击 +{detection.coefficient * 100:g}%'
        if detection is not None
        else '无'
    )
    multipliers = '，'.join(
        f'{name} ×{value:g}'
        for name, value in assessment.supplement_multipliers
    ) or '无'
    return {
        '标题': f'{value.facility.name} · {formation.name}',
        '字段': [
            {'键': '阵法', '值': str(formation.formation_id)},
            {'键': '品级', '值': str(assessment.grade_name)},
            {'键': '阵核', '值': '、'.join(assessment.core_names) or '—'},
            {'键': '承载', '值': f'{assessment.capacity:g}'},
            {'键': '冲击', '值': f'{assessment.impact:g}'},
            {'键': '节点', '值': f'{assessment.nodes}位 · 传导 {assessment.transmission:g}'},
            {'键': '辅材倍数', '值': multipliers},
            {'键': '检测', '值': detection_text},
            {'键': '难度', '值': detection.difficulty if detection is not None else '—'},
            {'键': pick('职位'), '值': str(value.role)},
            {'键': pick('材料来源'), '值': str(value.material_source)},
        ],
        '材料': [
            {
                '类别': str(material.category),
                '名称': str(material.name),
                '编号': str(material.item_id),
                '品级': str(material.grade_name),
                '数量': int(material.quantity),
            }
            for material in assessment.materials
            if material is not None
        ],
        '费用': {'键': pick('灵石消耗').split('{数量}')[0], '值': int(value.spirit_stone_cost)},
        '去向': pick('个人去向') if value.material_source == '个人纳戒' else pick('宗门去向'),
    }


__all__ = ['router']
