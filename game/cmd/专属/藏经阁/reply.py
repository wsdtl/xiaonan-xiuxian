"""藏经阁命令回复构造。"""

from __future__ import annotations

from collections.abc import Mapping

from game.features.zongmen_cangjing import CangjingCopy, CangjingPage
from message import M

from ...actions import message_actions
from ...presentation import sentence


def page(copy: CangjingCopy, value: CangjingPage, actions):
    builder = (
        M.document()
        .header(_text(copy, "标题"))
        .section("本宗道藏", icon="cultivation")
        .field("功法", M.text(value.total_entries, tone="mystic"))
    )
    if not value.entries:
        builder.line(M.status("空", tone="muted"), " ", _text(copy, "空"))
    for index, entry in enumerate(value.entries, start=1):
        builder.item(
            index,
            f"{entry.grade_name} · ",
            M.command(M.text(entry.name, tone="mystic"), f"查看 {entry.content_id}"),
            " · ",
            M.command(entry.content_id, f"查看 {entry.content_id}"),
            " · ",
            M.command(
                M.text("借阅至", tone="positive"),
                f"借阅功法 {entry.content_id}",
                submit=False,
            ),
        )
    builder.small(_text(copy, "页码", {"当前页": value.page, "总页数": value.page_count}))
    builder.small(_text(copy, "说明"))
    return builder.actions(message_actions(actions)).build()


def borrowed(copy: CangjingCopy, value):
    return (
        M.document()
        .header(_text(copy, "标题"))
        .section("借阅完成", icon="success")
        .line(M.status("借阅完成", tone="positive"))
        .line(
            _text(
                copy,
                "借阅", {"品级": value.technique.grade_name, "名称": value.technique.name, "槽位": value.slot},
            )
        )
        .build()
    )


def error(copy: CangjingCopy, message: str):
    return (
        M.document()
        .section(_text(copy, "错误"), icon="notice")
        .line(M.status("借阅失败", tone="danger"), " ", sentence(message))
        .build()
    )


def _text(copy: CangjingCopy, key: str, values: Mapping[str, object] | None = None) -> str:
    return copy.text[key].format_map(values or {})


__all__ = ["borrowed", "error", "page"]
