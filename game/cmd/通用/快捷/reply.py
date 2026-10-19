"""快捷命令回复构造。"""

from __future__ import annotations

from message import DocumentMessage, M

from game.features.najie import SpiritStoneView
from game.features.weizhi import StatusView


def spirit_stone(copy: dict, view: SpiritStoneView) -> DocumentMessage:
    builder = M.document().section(
        str(copy.get("标题") or "灵石"), icon="notice"
    )
    if not view.grades:
        builder.line(str(copy.get("没有") or "纳戒里没有灵石。"))
        return builder.build()
    builder.line(
        str(copy.get("合计") or "合计折算黄品当量 {total}。").format(
            total=view.total_units
        )
    )
    template = str(copy.get("某个品级") or "{grade} {quantity} 枚（折黄品 {units}）")
    for grade in view.grades:
        builder.line(
            template.format(
                grade=grade.grade_name,
                quantity=grade.quantity,
                units=grade.units,
            )
        )
    return builder.build()


def status(copy: dict, view: StatusView) -> DocumentMessage:
    builder = M.document().section(
        str(copy.get("标题") or "状态"), icon="notice"
    )
    builder.line(
        str(copy.get("位置") or "位置：{place}（{x}, {y}）").format(
            place=view.place_name, x=view.xy[0], y=view.xy[1]
        )
    )
    space = view.space_name or str(copy.get("地表") or "地表")
    builder.line(str(copy.get("空间") or "空间：{space}").format(space=space))
    if view.states:
        builder.line(
            str(copy.get("状态标签") or "状态：{states}").format(
                states="、".join(view.states)
            )
        )
    else:
        builder.line(str(copy.get("没有状态") or "状态：无"))
    return builder.build()
