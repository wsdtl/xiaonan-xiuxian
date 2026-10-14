"""意境命令回复构造。"""

from __future__ import annotations

from message import DocumentMessage, M


def _route_line(route, cap: int) -> str:
    """一行一路：点过的印阶与下一阶还差多少，没点过的印点它要多少道行。"""

    if not route.tier:
        return f"{route.name} 未点（点第一阶要 {route.next_cost} 道行）"
    if route.tier >= 9:
        return f"{route.name} {route.tier} 阶（已满九阶）"
    if route.tier >= cap:
        return f"{route.name} {route.tier} 阶（当前境界只到 {cap} 阶）"
    if route.missing:
        return f"{route.name} {route.tier} 阶（距{route.tier + 1}阶还差 {route.missing} 道行）"
    return f"{route.name} {route.tier} 阶（道行已足，可点{route.tier + 1}阶）"


def yijing_view(view) -> DocumentMessage:
    """`意境` 的回复：六条路各自的阶与六路共享的道行。"""

    builder = M.document()
    builder.section("意境", icon="status")
    builder.row(("道行", view.points), ("境界可点", f"{view.cap} 阶"))
    for route in view.routes:
        builder.line(_route_line(route, view.cap))
    builder.line("用法：意境 点 <路名或编号>")
    return builder.build()


def yijing_pointed(view, content_id: str) -> DocumentMessage:
    """点阶成功的回复：只印刚点的那一路，外加共享的道行。"""

    route = next(item for item in view.routes if item.content_id == content_id)
    builder = M.document()
    builder.section(route.name, icon="cultivation")
    builder.row(("阶", f"{route.tier} / {view.cap}"), ("道行", view.points))
    if route.tier >= 9:
        builder.line("这条路已满九阶。")
    elif route.next_cost and route.missing:
        builder.line(f"距{route.tier + 1}阶还差 {route.missing} 道行。")
    elif route.next_cost:
        builder.line(f"道行已足，可点{route.tier + 1}阶。")
    else:
        builder.line(f"当前境界只撑得到 {view.cap} 阶。")
    return builder.build()


def yijing_refused(reason: str) -> DocumentMessage:
    """被拒的回复（理由用人物核心给出的原文）。"""

    return M.document().section("意境", icon="notice").line(reason).build()
