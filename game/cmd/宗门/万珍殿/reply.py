"""万珍殿命令回复构造。"""

from __future__ import annotations

from ...presentation import error_document

from collections.abc import Sequence, Mapping
from ...actions import CommandAction, message_actions


from game.features.zongmen_wanzhen import (
    WanzhenCopy,
    WanzhenPage,
    WanzhenTransferResult,
)
from message import DocumentMessage, M

from ...presentation import sentence


def _treasure_name(entry: object, names: Mapping[str, str]) -> str:
    """条目上记的先天灵宝名——由玩法层放进结果里，渲染层只查表，不自己去问服务。"""

    identifier = str(getattr(entry, 'treasure_id', '') or '').strip()
    if not identifier:
        return ""
    return names.get(identifier, identifier)

def page(copy: WanzhenCopy, value: WanzhenPage, actions: Sequence[CommandAction]) -> DocumentMessage:
    builder = (
        M.document()

        .section(value.category, icon="game.bag")
    )
    # 计数为 0 时下面那句「空」已经把同一件事说过了，不必再说一遍。
    if value.total_entries:
        builder.field("珍物", value.total_entries)
    if not value.entries:
        builder.line(M.status("空", tone="muted"), " ", _text(copy, "空"))
    for index, entry in enumerate(value.entries, start=1):
        grade = entry.grade_name or ""
        # 玩家口径：物品[灵宝]，品级只做前缀；没有灵宝就只写物品名。
        shown = entry.name + ("[" + _treasure_name(entry, value.treasure_names) + "]" if _treasure_name(entry, value.treasure_names) else "")
        builder.item(
            index,
            f"{grade}",
            M.command(M.text(shown), f"查看 {entry.name}"),
            f" × {entry.quantity} · ",
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
    values = {"name": value.entry.name, "目标": value.target_name}
    return (
        M.document()

        .section(value.action, icon="game.success")
        .line(M.status("完成", tone="positive"), " ", _text(copy, key, values))
        .build()
    )


def error(copy: WanzhenCopy, message: str) -> DocumentMessage:
    # 形状统一走 error_document（game/cmd/presentation.py），行为与原来一致。
    return error_document(        _text(copy, "错误"), "game.pin_doc", "操作失败", sentence(message), tone="danger"
    )


def _text(copy: WanzhenCopy, key: str, values: Mapping[str, object] | None = None) -> str:
    return copy.text[key].format_map(values or {})


__all__ = ["error", "page", "transferred"]
