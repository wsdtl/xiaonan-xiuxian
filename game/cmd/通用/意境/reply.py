"""意境命令回复构造。"""

from __future__ import annotations

from message import DocumentMessage, M


def yijing_view(view) -> DocumentMessage:
    """`意境` 的回复：路、阶、道行与距下一阶还差多少。"""

    builder = M.document().header("意境")
    if view.content_id:
        builder.section("意境", icon="status")
        builder.row(("意境", view.display), ("阶", f"{view.tier} / {view.cap}"))
        builder.row(("道行", view.points))
        if view.tier >= 9:
            builder.line("意境已满九阶。")
        elif view.missing:
            builder.line(f"距{view.tier + 1}阶还差 {view.missing} 道行。")
        else:
            builder.line(f"道行已足，可升{view.tier + 1}阶。")
    else:
        builder.section("意境", icon="notice")
        builder.line("还没有选修意境。" + (f"道行 {view.points}。" if view.points else ""))
        builder.line("可修的路：" + "、".join(name for _, name in view.routes))
        builder.line("用法：意境 修 <路名>；选定之后：意境 升。")
    return builder.build()


def yijing_upgraded(view) -> DocumentMessage:
    """升阶成功的回复。"""

    return (
        M.document()
        .header("意境")
        .section("意境", icon="status")
        .row(("意境", view.display), ("阶", f"{view.tier} / {view.cap}"))
        .row(("道行", view.points))
        .build()
    )


def yijing_refused(reason: str) -> DocumentMessage:
    """被拒的回复（理由用人物核心给出的原文）。"""

    return M.document().header("意境").section("意境", icon="notice").line(reason).build()
