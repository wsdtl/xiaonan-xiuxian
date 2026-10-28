"""战报命令回复构造：个人 / 组队 / 宗门组队三栏。"""

from __future__ import annotations

from launch.paths import public_url
from message import DocumentMessage, M

from game.features.zhanbao import BattleReportFeature, MyReportSections


def _t(feature: BattleReportFeature, key: str) -> str:
    """取文案；数据集缺失时回退成键名，卡片不会空白。"""

    return str(feature.copy().get(key) or key)


def view(feature: BattleReportFeature, sections: MyReportSections) -> DocumentMessage:
    """三栏各自最近 5 条；空栏不出现，三类都空才给一次空态。"""

    builder = M.document().section(_t(feature, "说明"), icon="game.swords")
    if not (
        sections.personal
        or sections.team
        or sections.sect
    ):
        builder.line(M.status("空", tone="muted"), " ", _t(feature, "空"))
        return builder.build()
    for entries, label in (
        (sections.personal, "个人"),
        (sections.team, "组队"),
        (sections.sect, "宗门组队"),
    ):
        if not entries:
            continue
        builder.section(_t(feature, label), icon="game.swords")
        for entry in entries:
            builder.line(
                _t(feature, "条目").format_map(
                    {"类型": entry.kind, "时间": entry.finished_at}
                ),
                " · ",
                M.link(_t(feature, "打开"), public_url("battle", entry.report_id)),
            )
    return builder.build()
