"""纳戒命令回复构造。"""

from __future__ import annotations

from game.features.najie import NajieCategoryView, NajieEntry, NajieHome, NajiePage
from message import Action, M


def home(view: NajieHome):
    builder = M.document().header("纳戒")
    for category in view.categories:
        builder.section(category.name, icon=category.icon)
        for start in range(0, len(category.subcategories), 3):
            parts: list[object] = []
            for index, subcategory in enumerate(
                category.subcategories[start : start + 3]
            ):
                if index:
                    parts.append("　")
                parts.append(
                    M.command(
                        f"{subcategory.name} {_subcategory_summary(subcategory.entry_count, subcategory.total_quantity)}",
                        f"纳戒 {category.name} {subcategory.name}",
                    )
                )
            builder.line(*parts)
    return builder.build()


def category(view: NajieCategoryView):
    value = view.category
    builder = (
        M.document()
        .header(value.name)
        .section("分项", icon=value.icon)
    )
    for subcategory in value.subcategories:
        builder.line(
            M.command(subcategory.name, f"纳戒 {value.name} {subcategory.name}"),
            _subcategory_total(subcategory.entry_count, subcategory.total_quantity),
        )
    return builder.action(_home_action()).build()


def page(view: NajiePage):
    current_range = f"{view.start_index}-{view.end_index}" if view.entries else "0"
    section = "清单" if view.total_pages == 1 else f"清单 · 第{view.page}/{view.total_pages}页"
    builder = M.document().header(view.subcategory).section(section, icon=view.icon)
    if view.total_pages == 1:
        builder.field("合计", _subcategory_summary(view.entry_count, view.total_quantity))
    else:
        builder.row(("种类", f"{view.entry_count}种"), ("本页", current_range))
        if view.total_quantity != view.entry_count:
            builder.field("总数", f"{view.total_quantity}份")
    if not view.entries:
        builder.line(f"尚无{view.subcategory}。")
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
        .action(_home_action())
        .build()
    )


def _entry_parts(entry: NajieEntry) -> tuple[object, ...]:
    has_stable_id = entry.content_id.isdigit() and len(entry.content_id) == 6
    name: object = (
        M.command(entry.name, f"查看 {entry.content_id}")
        if has_stable_id
        else entry.name
    )
    parts: list[object] = [name]
    if entry.grade_name:
        parts.extend((" · ", entry.grade_name))
    if entry.category in {"物品", "修行资粮", "器藏"} or entry.quantity > 1:
        parts.append(f" × {entry.quantity}")
    if entry.equipped_slots:
        parts.extend((" · 已装", "、".join(entry.equipped_slots)))
    if entry.material_total is not None:
        parts.append(f" · 投入{entry.material_total}份")
    if entry.category == "道藏" and entry.grade_name:
        parts.extend(
            (
                " · ",
                M.command(
                    "装配",
                    f"人物装配 功法 {entry.content_id} {entry.grade_id}",
                    submit=False,
                ),
            )
        )
    return tuple(parts)


def _home_action() -> Action:
    return Action(
        "najie.home", "返回纳戒", "纳戒", behavior="callback", style="secondary"
    )


def _subcategory_total(entry_count: int, total_quantity: int) -> str:
    return f" · {_subcategory_summary(entry_count, total_quantity)}"


def _subcategory_summary(entry_count: int, total_quantity: int) -> str:
    if entry_count == total_quantity:
        return f"{entry_count}种"
    return f"{entry_count}种/{total_quantity}份"


__all__ = ["category", "error", "home", "page"]
