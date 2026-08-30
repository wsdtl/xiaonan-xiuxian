"""藏经阁命令回复构造。"""

from __future__ import annotations

from game.features.zongmen_cangjing import CangjingCopy, CangjingPage
from message import M

from ...actions import message_actions
from ...presentation import sentence


def page(copy: CangjingCopy, value: CangjingPage, actions):
    builder = (
        M.document()
        .header(_text(copy, "标题"))
        .section("本宗道藏", icon="cultivation")
        .field("功法", value.total_entries)
    )
    if not value.entries:
        builder.line(_text(copy, "空"))
    for index, entry in enumerate(value.entries, start=1):
        builder.item(
            index,
            f"{entry.grade_name} · ",
            M.command(entry.name, f"查看 {entry.content_id}"),
            " · ",
            M.command(entry.content_id, f"查看 {entry.content_id}"),
            " · ",
            M.command(
                "借阅至",
                f"借阅功法 {entry.content_id}",
                submit=False,
            ),
        )
    builder.line(_text(copy, "页码", 当前页=value.page, 总页数=value.page_count))
    builder.line(_text(copy, "说明"))
    return builder.actions(message_actions(actions)).build()


def borrowed(copy: CangjingCopy, value):
    return (
        M.document()
        .header(_text(copy, "标题"))
        .section("借阅完成", icon="success")
        .line(
            _text(
                copy,
                "借阅",
                品级=value.technique.grade_name,
                名称=value.technique.name,
                槽位=value.slot,
            )
        )
        .build()
    )


def error(copy: CangjingCopy, message: str):
    return (
        M.document().section(_text(copy, "错误"), icon="notice").line(sentence(message)).build()
    )


def _text(copy: CangjingCopy, key: str, **values: object) -> str:
    return copy.text[key].format_map(values)


__all__ = ["borrowed", "error", "page"]
