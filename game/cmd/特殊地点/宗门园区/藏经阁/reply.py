"""藏经阁命令回复构造。"""

from __future__ import annotations

from ....presentation import error_document

from collections.abc import Sequence, Mapping
from ....actions import CommandAction, message_actions


from game.features.zongmen_cangjing import CangjingAction, CangjingCopy, CangjingPage
from message import DocumentMessage, M

from ....presentation import sentence


def page(copy: CangjingCopy, value: CangjingPage, actions: Sequence[CommandAction]) -> DocumentMessage:
    builder = (
        M.document()

        .section(_text(copy, "标题"), icon="cultivation")
    )
    if value.page == 1:
        builder.line(_text(copy, "介绍"))
    # 计数为 0 时下面那句「空」已经把同一件事说过了，不必再说一遍。
    if value.total_entries:
        builder.field("功法", M.text(value.total_entries, tone="mystic"))
    if not value.entries:
        builder.line(M.status("空", tone="muted"), " ", _text(copy, "空"))
    for index, entry in enumerate(value.entries, start=1):
        builder.item(
            index,
            # 卡面全中文、不印编号；名字只作显示，点它出「查看 | 藏经阁 借阅」两条分支。
            # 分支参数用名字（聊天命令本来就收名字），编号只在 help 里出现、不参与联动。
            M.command(
                f"{entry.grade_name}{entry.name}",
                f"查看 {entry.name} | 藏经阁 借阅 {entry.name}",
            ),
        )
    # 只有一页就不报页码——灵藏与万珍殿本来就是这个口径，藏经阁跟上。
    if value.page_count > 1:
        builder.small(_text(copy, "页码", {"当前页": value.page, "总页数": value.page_count}))
    builder.small(_text(copy, "说明"))
    builder.small(_text(copy, "分支"))
    return builder.actions(message_actions(actions)).build()


def borrow_prompt(
    copy: CangjingCopy, identifier: str, slots: Sequence[int]
) -> DocumentMessage:
    actions = tuple(
        CangjingAction(
            f"cangjing.borrow.{slot}",
            _text(copy, "槽位按钮", {"槽位": slot}),
            f"藏经阁 借阅 {identifier} {slot}",
            "callback",
            "primary",
        )
        for slot in slots
    ) + (
        CangjingAction(
            "cangjing.back",
            _text(copy, "返回藏经阁"),
            "藏经阁",
            "callback",
            "secondary",
        ),
    )
    return (
        M.document()
        .section(_text(copy, "选择槽位"), icon="cultivation")
        .line(_text(copy, "选择槽位说明", {"名称": identifier}))
        .actions(message_actions(actions))
        .build()
    )


def borrowed(copy: CangjingCopy, value: CangjingPage) -> DocumentMessage:
    return (
        M.document()

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
    # 形状统一走 error_document（game/cmd/presentation.py），行为与原来一致。
    return error_document(        _text(copy, "错误"), "notice", "借阅失败", sentence(message), tone="danger"
    )


def _text(copy: CangjingCopy, key: str, values: Mapping[str, object] | None = None) -> str:
    return copy.text[key].format_map(values or {})


__all__ = ["borrowed", "error", "page"]
