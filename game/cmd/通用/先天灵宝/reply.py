"""先天灵宝回复构造。"""

from __future__ import annotations

from ...actions import CommandAction
from ...presentation import error_document

from typing import Sequence

from game.features.xiantian_lingbao import InnateTreasure

from message import DocumentBuilder, DocumentMessage, M

from game.features.xiantian_lingbao import (
    InnateTreasureFeature,
    InnateTreasureEquipResult,
    InnateTreasureView,
)


def view(feature: InnateTreasureFeature, result: InnateTreasureView) -> DocumentMessage:
    builder = M.document().header(feature.copy("标题"))
    if result.active is None:
        builder.section(feature.copy("当前执掌"), icon="status").line(
            M.status("未执掌", tone="muted"), " ", feature.copy("未执掌")
        )
    else:
        builder.section(feature.copy("当前执掌"), icon="status").line(
            M.status("已执掌", tone="positive")
        )
        _append_treasure(builder, result.active)
    builder.section(feature.copy("灵宝谱"), icon="inventory")
    if not result.owned:
        builder.line(M.status("空", tone="muted"), " ", feature.copy("未得"))
    else:
        for index, treasure in enumerate(result.owned, start=1):
            builder.item(
                index,
                M.command(
                    M.text(treasure.name),
                    f"查看 {treasure.name}",
                ),
                f" · {treasure.authority}",
            )
            builder.small(treasure.description)
    if result.page_count > 1:
        builder.small(
            feature.copy("页码", {"当前页": result.page, "总页数": result.page_count})
        )
    return builder.build()


def catalog(feature: InnateTreasureFeature, result: InnateTreasureView) -> DocumentMessage:
    """灵宝谱：列这个世界里**一共存在**的先天灵宝（与玩家有没有无关）。"""

    builder = M.document().header(feature.copy("谱标题"))
    builder.section(feature.copy("谱标题"), icon="inventory").line(
        feature.copy("谱说明", {"总数": result.total_count})
    )
    for index, treasure in enumerate(result.owned, start=1):
        builder.item(
            index,
            M.command(M.text(treasure.name), f"查看 {treasure.name}"),
        )
        builder.small(f"· {feature.copy('谱行权柄')}：{treasure.authority}")
        builder.small(f"· {feature.copy('谱行加成')}：{_effect(treasure)}")
    if result.page_count > 1:
        builder.small(
            feature.copy("页码", {"当前页": result.page, "总页数": result.page_count})
        )
    return builder.build()


def equipped(feature: InnateTreasureFeature, result: InnateTreasureEquipResult) -> DocumentMessage:
    treasure = result.treasure
    return (
        M.document()
        .section(feature.copy("标题"), icon="skill")
        .line(
            M.status("执掌完成", tone="positive"),
            " ",
            feature.copy("执掌成功", {"名称": treasure.name, "权柄": treasure.authority}),
        )
        .field(feature.copy("效果"), _effect(treasure))
        .build()
    )


def error(
    feature: XiantianLingbaoFeature, message: str, actions: Sequence[CommandAction] = ()
) -> DocumentMessage:
    """失败回执：标题与状态词取自展示数据集，动作由玩法层给。"""

    return error_document(
        feature.copy("错误标题"),
        "notice",
        feature.copy("错误失败"),
        message,
        tone="danger",
        actions=actions,
        hint=feature.copy("错误尾注"),
    )


def _append_treasure(builder: DocumentBuilder, treasure: InnateTreasure) -> None:
    builder.field(
        "名称",
        M.command(
            M.text(treasure.name),
            f"查看 {treasure.name}",
        ),
    )
    builder.field("权柄", treasure.authority)
    builder.field("说明", treasure.description)
    builder.field("规则权柄", _effect(treasure))


def _effect(treasure: InnateTreasure) -> str:
    return f"{treasure.effect.node}：{treasure.effect.ability}"


__all__ = ["catalog", "equipped", "error", "view"]
