"""灵藏命令回复构造。"""

from __future__ import annotations

from game.features.zongmen_lingcang import LingcangCopy, LingcangPage
from message import M

from ...actions import message_actions
from ...presentation import sentence


def page(copy: LingcangCopy, value: LingcangPage, actions):
    builder = (
        M.document()
        .header(_text(copy, "标题"))
        .section(value.category, icon="inventory")
        .row((_text(copy, "灵石"), value.spirit_stones), ("材料", value.total_entries))
    )
    if not value.entries:
        builder.line(_text(copy, "空"))
    for index, entry in enumerate(value.entries, start=1):
        builder.item(
            index,
            f"{entry.grade_name}{entry.name} × {entry.quantity}",
        ).line(f"{entry.category} · {entry.content_id}")
    if value.page_count > 1:
        builder.line(_text(copy, "页码", 当前页=value.page, 总页数=value.page_count))
    return builder.actions(message_actions(actions)).build()


def donated_material(copy: LingcangCopy, result):
    entry = result.entry
    if entry is None:
        return error(copy, "灵藏捐献结果缺少材料条目")
    builder = (
        M.document()
        .header(_text(copy, "标题"))
        .section("捐入灵藏", icon="success")
        .line(
            _text(
                copy,
                "捐入材料",
                品级=entry.grade_name,
                名称=entry.name,
                数量=entry.quantity,
            )
        )
    )
    if result.contribution:
        builder.field("宗门贡献", f"+{result.contribution}")
    if result.treasure_activation is not None:
        activation = result.treasure_activation
        builder.section("先天灵宝", icon="item").field(
            activation.name, activation.summary
        )
    return builder.build()


def donated_stones(copy: LingcangCopy, quantity: int, result):
    builder = (
        M.document()
        .header(_text(copy, "标题"))
        .section("捐入灵藏", icon="success")
        .line(_text(copy, "捐入灵石", 数量=quantity, 余额=result.spirit_stones))
    )
    if result.contribution:
        builder.field("宗门贡献", f"+{result.contribution}")
    if result.treasure_activation is not None:
        activation = result.treasure_activation
        builder.section("先天灵宝", icon="item").field(
            activation.name, activation.summary
        )
    return builder.build()


def error(copy: LingcangCopy, message: str):
    return (
        M.document().section(_text(copy, "错误"), icon="notice").line(sentence(message)).build()
    )


def _text(copy: LingcangCopy, key: str, **values: object) -> str:
    return copy.text[key].format_map(values)


__all__ = ["donated_material", "donated_stones", "error", "page"]
