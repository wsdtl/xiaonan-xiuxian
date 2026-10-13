"""战报命令回复构造：我的最近未过期战报。"""

from __future__ import annotations

from launch.paths import public_url
from message import DocumentMessage, M

from game.features.zhanbao import BattleReportFeature, MyReportPage


def _t(feature: BattleReportFeature, key: str) -> str:
    """取文案；数据集缺失时回退成键名，卡片不会空白。"""

    return str(feature.copy().get(key) or key)


def view(feature: BattleReportFeature, page: MyReportPage) -> DocumentMessage:
    """把一页「我的战报」拼成卡：倒序条目、每条一个打开链接、页码与总数。"""

    builder = M.document().header(_t(feature, "标题"))
    # line/row/item 必须属于 section；分节恒定存在（标题用有信息的一句），
    # 空列表走 line＋状态点，照宗门战 history 的成品写法——不另开空栏目。
    builder.section(_t(feature, "说明"), icon="combat")
    if page.entries:
        builder.field(_t(feature, "分类"), _t(feature, "总数").format_map({"数量": page.total}))
    else:
        builder.line(M.status("空", tone="muted"), " ", _t(feature, "空"))
    for entry in page.entries:
        builder.line(
            _t(feature, "条目").format_map({"类型": entry.kind, "时间": entry.finished_at}),
            M.link(_t(feature, "打开"), public_url("battle", entry.report_id)),
        )
        if entry.participants:
            builder.line(_t(feature, "参与者").format_map({"名单": "、".join(entry.participants)}))
    if page.total:
        page_size = max(1, page.size)
        total_pages = max(1, (page.total + page_size - 1) // page_size)
        builder.line(_t(feature, "页码").format_map({"页": page.page, "总页": total_pages}))
    return builder.build()
