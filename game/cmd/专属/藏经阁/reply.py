"""藏经阁命令回复构造。"""

from __future__ import annotations

from collections.abc import Sequence, Mapping
from ...actions import CommandAction, message_actions


from game.features.zongmen_cangjing import CangjingCopy, CangjingPage
from message import DocumentMessage, M

from ...presentation import sentence


def page(copy: CangjingCopy, value: CangjingPage, actions: Sequence[CommandAction]) -> DocumentMessage:
    builder = (
        M.document()
        .header(_text(copy, "标题"))
        .section("本宗道藏", icon="cultivation")
    )
    # 计数为 0 时下面那句「空」已经把同一件事说过了，不必再说一遍。
    if value.total_entries:
        builder.field("功法", M.text(value.total_entries, tone="mystic"))
    if not value.entries:
        builder.line(M.status("空", tone="muted"), " ", _text(copy, "空"))
    for index, entry in enumerate(value.entries, start=1):
        builder.item(
            index,
            f"{entry.grade_name} · ",
            # 同一份功法有两条命令（查看 / 借阅功法），参数尾巴一样，合成一个分支控件：
            # 点一次回选择菜单，够参数的直接发、还差槽位的只填入。
            M.command(entry.name, f"查看|借阅功法 {entry.content_id}"),
            " · ",
            entry.content_id,
        )
    # 只有一页就不报页码——灵藏与万珍殿本来就是这个口径，藏经阁跟上。
    if value.page_count > 1:
        builder.small(_text(copy, "页码", {"当前页": value.page, "总页数": value.page_count}))
    builder.small(_text(copy, "说明"))
    return builder.actions(message_actions(actions)).build()


def borrowed(copy: CangjingCopy, value: CangjingPage) -> DocumentMessage:
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


def error(copy: CangjingCopy, message: str) -> DocumentMessage:
    return (
        M.document()
        .section(_text(copy, "错误"), icon="notice")
        .line(M.status("借阅失败", tone="danger"), " ", sentence(message))
        .build()
    )


def _text(copy: CangjingCopy, key: str, values: Mapping[str, object] | None = None) -> str:
    return copy.text[key].format_map(values or {})


__all__ = ["borrowed", "error", "page"]
