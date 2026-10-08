"""种族图鉴回复构造。"""

from __future__ import annotations

from game.features.zhongzu import RaceEntry, RaceOverview, ZhongzuCopy
from message import Action, DocumentMessage, M


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
        # 名字本身即入口：与角色页的物件/构筑一致，标签保持正文（带 tone 会被推进公式，
        # 而 QQ 不解析公式里的链接）。
        builder.line(
            M.command(race.name, f"种族 {race.number}"),
            " · " + "/".join(race.tiers),
        )
    # 整句提示用正文行：一是 small 会被推进公式（不渲染公式的客户端会露出 LaTeX 源码），
    # 二是 note 渲染成第 1 层无冒号的行，会被「空栏目」判据当成栏目标题。
    builder.line(_text(copy, "总览", "提示"))
    total = len(overview.lineages)
    actions: list[Action] = []
    if index > 1:
        actions.append(
            Action("zhongzu.previous", "上一页", f"种族 {index - 1}",
                   behavior="callback", style="secondary")
        )
    if index < total:
        actions.append(
            Action("zhongzu.next", "下一页", f"种族 {index + 1}",
                   behavior="callback", style="secondary")
        )
    if actions:
        builder.actions(actions)
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
    if race.cost:
        builder.line(_text(copy, "详情", "本相代价").format_map({
            "本相": _text(copy, "详情", "规则分隔").join(race.benefits),
            "代价": race.cost,
        }))
    else:
        builder.line(race.flavor)
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
