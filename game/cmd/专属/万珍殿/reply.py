"""万珍殿命令回复构造。"""

from __future__ import annotations

from game.features.zongmen_wanzhen import (
    WanzhenCopy,
    WanzhenPage,
    WanzhenTransferResult,
)
from message import M

from ...actions import message_actions
from ...presentation import sentence


def page(copy: WanzhenCopy, value: WanzhenPage, actions):
    builder = (
        M.document()
        .header(_text(copy, "标题"))
        .section(value.category, icon="inventory")
        .field("珍物", value.total_entries)
    )
    if not value.entries:
        builder.line(_text(copy, "空"))
    for index, entry in enumerate(value.entries, start=1):
        grade = entry.grade_name or ""
        builder.item(
            index,
            f"{grade}",
            M.command(entry.name, f"查看 {entry.content_id}"),
            f" × {entry.quantity} · ",
            M.command(entry.content_id, f"查看 {entry.content_id}"),
        )
        if entry.materials:
            builder.line(
                "实际投入："
                + "、".join(f"{key}{amount}" for key, amount in entry.materials)
            )
    if value.page_count > 1:
        builder.line(_text(copy, "页码", 当前页=value.page, 总页数=value.page_count))
    return builder.actions(message_actions(actions)).build()


def transferred(copy: WanzhenCopy, value: WanzhenTransferResult):
    key = "捐入" if value.action == "存入" else "发放"
    values = {"名称": value.entry.name, "目标": value.target_name}
    return (
        M.document()
        .header(_text(copy, "标题"))
        .section(value.action, icon="success")
        .line(_text(copy, key, **values))
        .field("编号", value.entry.content_id)
        .build()
    )


def error(copy: WanzhenCopy, message: str):
    return (
        M.document()
        .section(_text(copy, "错误"), icon="notice")
        .line(sentence(message))
        .build()
    )


def _text(copy: WanzhenCopy, key: str, **values: object) -> str:
    return copy.text[key].format_map(values)


__all__ = ["error", "page", "transferred"]
