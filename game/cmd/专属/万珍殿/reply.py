"""万珍殿命令回复构造。"""

from __future__ import annotations

from collections.abc import Sequence, Mapping
from ...actions import CommandAction, message_actions


from game.features.zongmen_wanzhen import (
    WanzhenCopy,
    WanzhenPage,
    WanzhenTransferResult,
)
from message import DocumentMessage, M

from ...presentation import sentence


def page(copy: WanzhenCopy, value: WanzhenPage, actions: Sequence[CommandAction]) -> DocumentMessage:
    builder = (
        M.document()
        .header(_text(copy, "标题"))
        .section(value.category, icon="inventory")
        .field("珍物", value.total_entries)
    )
    if not value.entries:
        builder.line(M.status("空", tone="muted"), " ", _text(copy, "空"))
    for index, entry in enumerate(value.entries, start=1):
        grade = entry.grade_name or ""
        builder.item(
            index,
            f"{grade}",
            M.command(M.text(entry.name), f"查看 {entry.content_id}"),
            f" × {entry.quantity} · ",
            M.command(entry.content_id, f"查看 {entry.content_id}"),
        )
        if entry.materials:
            builder.small(
                "实际投入："
                + "、".join(f"{key}{amount}" for key, amount in entry.materials)
            )
    if value.page_count > 1:
        builder.small(_text(copy, "页码", {"当前页": value.page, "总页数": value.page_count}))
    return builder.actions(message_actions(actions)).build()


def transferred(copy: WanzhenCopy, value: WanzhenTransferResult) -> DocumentMessage:
    key = "捐入" if value.action == "存入" else "发放"
    values = {"名称": value.entry.name, "目标": value.target_name}
    return (
        M.document()
        .header(_text(copy, "标题"))
        .section(value.action, icon="success")
        .line(M.status("完成", tone="positive"), " ", _text(copy, key, values))
        .field("编号", value.entry.content_id)
        .build()
    )


def error(copy: WanzhenCopy, message: str) -> DocumentMessage:
    return (
        M.document()
        .section(_text(copy, "错误"), icon="notice")
        .line(M.status("操作失败", tone="danger"), " ", sentence(message))
        .build()
    )


def _text(copy: WanzhenCopy, key: str, values: Mapping[str, object] | None = None) -> str:
    return copy.text[key].format_map(values or {})


__all__ = ["error", "page", "transferred"]
