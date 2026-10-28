"""灵藏命令回复构造。"""

from __future__ import annotations

from ...presentation import error_document, linked_name_line

from game.features.zongmen_lingcang import SectAssetTransfer

from collections.abc import Sequence, Mapping
from ...actions import CommandAction, message_actions


from game.features.zongmen_lingcang import LingcangCopy, LingcangPage
from message import DocumentMessage, M

from ...presentation import sentence


def page(copy: LingcangCopy, value: LingcangPage, actions: Sequence[CommandAction]) -> DocumentMessage:
    builder = M.document().section(value.category, icon="game.bag")
    # 两个数都是 0 时下面那句「空」已经把同一件事说过了，不必再说一遍。
    if value.spirit_stones or value.total_entries:
        builder.row(
            (_text(copy, "灵石"), M.text(value.spirit_stones, tone="cultivation")),
            ("材料", M.text(value.total_entries, tone="emphasis")),
        )
    if not value.entries:
        builder.line(M.status("空", tone="muted"), " ", _text(copy, "空"))
    for index, entry in enumerate(value.entries, start=1):
        builder.item(
            index,
            M.command(
                M.text(f"{entry.grade_name}{entry.name}"),
                f"查看 {entry.name}",
            ),
            f" × {entry.quantity}",
        ).small(entry.category)
    if value.page_count > 1:
        builder.small(_text(copy, "页码", {"当前页": value.page, "总页数": value.page_count}))
    return builder.actions(message_actions(actions)).build()


def donated_material(copy: LingcangCopy, result: SectAssetTransfer) -> DocumentMessage:
    entry = result.entry
    if entry is None:
        return error(copy, "灵藏捐献结果缺少材料条目")
    builder = (
        M.document()

        .section("捐入灵藏", icon="game.success")
        .line(M.status("捐献完成", tone="positive"))
        .line(
            *linked_name_line(
                _text(
                    copy,
                    "捐入材料",
                    {
                        "品级": entry.grade_name,
                        "名称": "\u0000",
                        "数量": entry.quantity,
                    },
                ),
                entry.name,
            )
        )
    )
    if result.contribution:
        builder.field("宗门贡献", M.text(f"+{result.contribution}", tone="positive"))
    if result.treasure_activation is not None:
        activation = result.treasure_activation
        builder.section("灵宝", icon="game.box").field(
            activation.name, activation.summary
        )
    return builder.build()


def donated_stones(copy: LingcangCopy, quantity: int, result: SectAssetTransfer) -> DocumentMessage:
    builder = (
        M.document()

        .section("捐入灵藏", icon="game.success")
        .line(M.status("捐献完成", tone="positive"))
        .line(_text(copy, "捐入灵石", {"数量": quantity, "余额": result.spirit_stones}))
    )
    if result.contribution:
        builder.field("宗门贡献", M.text(f"+{result.contribution}", tone="positive"))
    if result.treasure_activation is not None:
        activation = result.treasure_activation
        builder.section("灵宝", icon="game.box").field(
            activation.name, activation.summary
        )
    return builder.build()


def error(copy: LingcangCopy, message: str) -> DocumentMessage:
    # 形状统一走 error_document（game/cmd/presentation.py），行为与原来一致。
    return error_document(        _text(copy, "错误"), "game.pin_doc", "捐献失败", sentence(message), tone="danger"
    )


def _text(copy: LingcangCopy, key: str, values: Mapping[str, object] | None = None) -> str:
    return copy.text[key].format_map(values or {})


__all__ = ["donated_material", "donated_stones", "error", "page"]
