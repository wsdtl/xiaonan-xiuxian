"""种族图鉴回复构造。"""

from __future__ import annotations

from game.features.zhongzu import RaceEntry, RaceOverview, ZhongzuCopy
from message import DocumentMessage, M


def _text(copy: ZhongzuCopy, section: str, key: str) -> str:
    return copy.text[section][key]


def page(copy: ZhongzuCopy, overview: RaceOverview, index: int) -> DocumentMessage:
    """一页一个族系：族系名 + 该族全部种族 + 提示。"""

    lineage = overview.lineages[index - 1]
    builder = M.document().header(_text(copy, "总览", "标题"))
    builder.section(
        lineage.name
        + " · "
        + _text(copy, "总览", "页码").format_map(
            {"当前页": index, "总页数": len(overview.lineages)}
        ),
        icon="character",
    )
    if index == 1:
        builder.line(_text(copy, "总览", "引言").format_map(
            {"总数": overview.total, "族系数": len(overview.lineages)}
        ))
    for race in lineage.races:
        builder.line(M.text(race.name, tone="emphasis"), " · " + "/".join(race.tiers))
    builder.small(_text(copy, "总览", "提示"))
    return builder.build()


def detail(copy: ZhongzuCopy, race: RaceEntry) -> DocumentMessage:
    """单个种族详情：基础事实 + 天生规则 + 说明，全部来自登记表。"""

    builder = M.document().header(
        _text(copy, "详情", "标题").format_map({"种族": race.name})
    )
    builder.section(_text(copy, "详情", "基础"), icon="character").field(
        _text(copy, "详情", "编号"), M.text(race.number, tone="emphasis")
    ).field(
        _text(copy, "详情", "族系"), race.lineage
    ).field(
        _text(copy, "详情", "档次"), "/".join(race.tiers)
    ).field(
        _text(copy, "详情", "寿元"), M.text(f"×{race.lifespan:g}", tone="emphasis")
    )
    builder.section(_text(copy, "详情", "天生规则"), icon="skill")
    for name, source in race.rules:
        if source:
            builder.line(_text(copy, "详情", "规则来源").format_map(
                {"名称": name, "来源": source}
            ))
        else:
            builder.line(_text(copy, "详情", "规则").format_map({"名称": name}))
    builder.section(_text(copy, "详情", "说明"), icon="notice")
    builder.line(race.summary)
    return builder.build()


def missing(copy: ZhongzuCopy, query: str) -> DocumentMessage:
    """按编号和名字都找不到时给出的回执。"""

    return (
        M.document()
        .section(_text(copy, "详情", "基础"), icon="notice")
        .line(M.status("未找到", tone="danger"), " ", _text(copy, "错误", "未找到").format_map({"查询": query}))
        .build()
    )


def invalid_page(copy: ZhongzuCopy, overview: RaceOverview) -> DocumentMessage:
    """页码超出族系数时给出的回执。"""

    return (
        M.document()
        .section(_text(copy, "总览", "标题"), icon="notice")
        .line(M.status("页码有误", tone="warning"), " ", _text(copy, "错误", "页码有误").format_map(
            {"总页数": len(overview.lineages)}
        ))
        .build()
    )


__all__ = ["detail", "invalid_page", "missing", "page"]
