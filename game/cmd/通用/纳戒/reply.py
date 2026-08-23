"""纳戒命令回复构造。"""

from __future__ import annotations

from game.features.najie import NajieCategoryView, NajieEntry, NajieHome, NajiePage
from message import Action, M


def home(view: NajieHome):
    builder = M.document().header("晓楠修仙 · 纳戒")
    for category in view.categories:
        builder.section(category.name, icon=category.icon)
        builder.row(("条目", category.entry_count), ("总数", category.total_quantity))
        for start in range(0, len(category.subcategories), 3):
            parts: list[object] = []
            for index, subcategory in enumerate(
                category.subcategories[start : start + 3]
            ):
                if index:
                    parts.append("　")
                parts.append(
                    M.command(
                        f"{subcategory.name} {subcategory.entry_count}",
                        f"纳戒 {category.name} {subcategory.name}",
                    )
                )
            builder.line(*parts)
    return builder.build()


def category(view: NajieCategoryView):
    value = view.category
    builder = (
        M.document()
        .header(f"纳戒 · {value.name}")
        .section("总览", icon=value.icon)
        .row(("条目", value.entry_count), ("总数", value.total_quantity))
        .section("分类", icon=value.icon)
    )
    for subcategory in value.subcategories:
        builder.line(
            M.command(subcategory.name, f"纳戒 {value.name} {subcategory.name}"),
            f" · {subcategory.entry_count}条 / 共{subcategory.total_quantity}份",
        )
    return builder.action(_home_action()).build()


def page(view: NajiePage):
    current_range = f"{view.start_index}-{view.end_index}" if view.entries else "0"
    builder = (
        M.document()
        .header(f"纳戒 · {view.subcategory}")
        .section(f"第{view.page}/{view.total_pages}页", icon=view.icon)
        .row(("条目", view.entry_count), ("总数", view.total_quantity))
        .field("当前", current_range)
        .section("藏中所录", icon=view.icon)
    )
    if not view.entries:
        builder.line("当前小类尚无内容。")
    for index, entry in enumerate(view.entries, start=view.start_index):
        builder.item(index, *_entry_parts(entry))
    actions: list[Action] = []
    if view.page > 1:
        actions.append(
            Action(
                "najie.previous",
                "上一页",
                f"纳戒 {view.category} {view.subcategory} {view.page - 1}",
                behavior="callback",
                style="secondary",
            )
        )
    if view.page < view.total_pages:
        actions.append(
            Action(
                "najie.next",
                "下一页",
                f"纳戒 {view.category} {view.subcategory} {view.page + 1}",
                behavior="callback",
                style="secondary",
            )
        )
    actions.extend(
        (
            Action(
                "najie.category",
                f"返回{view.category}",
                f"纳戒 {view.category}",
                behavior="callback",
                style="secondary",
            ),
            _home_action(),
        )
    )
    return builder.actions(actions).build()


def error(message: str):
    return (
        M.document()
        .section("纳戒", icon="notice")
        .line(message)
        .line("使用“纳戒”返回分类首页。")
        .action(_home_action())
        .build()
    )


def _entry_parts(entry: NajieEntry) -> tuple[object, ...]:
    name: object = entry.name
    if entry.category == "物品":
        name = M.command(entry.name, f"查看 {entry.content_id}")
    parts: list[object] = [name]
    if entry.grade_name:
        parts.extend((" · ", entry.grade_name))
    if entry.category in {"物品", "修行资粮", "器藏"} or entry.quantity > 1:
        parts.append(f" × {entry.quantity}")
    if entry.equipped_slots:
        parts.extend((" · 已装", "、".join(entry.equipped_slots)))
    if entry.material_total is not None:
        parts.append(f" · 投入{entry.material_total}份")
    return tuple(parts)


def _home_action() -> Action:
    return Action(
        "najie.home", "返回纳戒", "纳戒", behavior="callback", style="secondary"
    )


__all__ = ["category", "error", "home", "page"]
