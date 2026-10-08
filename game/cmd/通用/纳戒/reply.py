"""纳戒命令回复构造。"""

from __future__ import annotations

from game.features.najie import NajieCategoryView, NajieEntry, NajieHome, NajiePage
from message import DocumentMessage, Action, M


def _has_content(item: object) -> bool:
    """这个分项里到底有没有东西——空分项不该做成可点条目。"""

    return bool(item.entry_count or item.total_quantity)


def home(view: NajieHome) -> DocumentMessage:
    builder = M.document().header("纳戒")
    empty = 0
    for category in view.categories:
        # 空分项不做成可点条目：点进去只有一页空清单，等于白翻一页。
        filled = tuple(item for item in category.subcategories if _has_content(item))
        empty += len(category.subcategories) - len(filled)
        if not filled:
            continue
        builder.section(category.name, icon=category.icon)
        for start in range(0, len(filled), 3):
            parts: list[object] = []
            for index, subcategory in enumerate(filled[start : start + 3]):
                if index:
                    parts.append("　")
                parts.append(
                    M.command(
                        f"{subcategory.name} {_subcategory_summary(subcategory.entry_count, subcategory.total_quantity)}",
                        f"纳戒 {category.name} {subcategory.name}",
                    )
                )
            builder.line(*parts)
    if empty:
        builder.small(f"另有 {empty} 个分项暂无内容，拿到后会出现在这里。")
    return builder.build()


def category(view: NajieCategoryView) -> DocumentMessage:
    value = view.category
    builder = M.document().header(value.name).section("分项", icon=value.icon)
    filled = tuple(item for item in value.subcategories if _has_content(item))
    for subcategory in filled:
        builder.line(
            M.command(subcategory.name, f"纳戒 {value.name} {subcategory.name}"),
            _subcategory_total(subcategory.entry_count, subcategory.total_quantity),
        )
    if len(filled) != len(value.subcategories):
        builder.small("其余分项暂无内容。")
    return builder.action(_home_action()).build()


def page(view: NajiePage) -> DocumentMessage:
    current_range = f"{view.start_index}-{view.end_index}" if view.entries else "0"
    section = (
        "清单"
        if view.total_pages == 1
        else f"清单 · 第{view.page}/{view.total_pages}页"
    )
    builder = M.document().header(view.subcategory).section(section, icon=view.icon)
    if view.total_pages == 1:
        builder.field(
            "合计",
            M.text(
                _subcategory_summary(view.entry_count, view.total_quantity),
                tone="emphasis",
            ),
        )
    else:
        builder.row(("种类", f"{view.entry_count}种"), ("本页", current_range))
        if view.total_quantity != view.entry_count:
            builder.field("总数", f"{view.total_quantity}份")
    if not view.entries:
        builder.line(M.status("空", tone="muted"), f" 尚无{view.subcategory}。")
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


def error(message: str) -> DocumentMessage:
    return (
        M.document()
        .section("纳戒", icon="notice")
        .line(M.status("查询失败", tone="danger"), " ", message)
        .action(_home_action())
        .build()
    )


def _entry_parts(entry: NajieEntry) -> tuple[object, ...]:
    has_stable_id = entry.content_id.isdigit() and len(entry.content_id) == 6
    command = f"查看 {entry.content_id}"
    if entry.category == "道藏" and entry.grade_id:
        # 同一条功法有两个动作、参数还不一样（查看只吃编号，装配要品类与器阶），
        # 用「每条分支自带完整命令」的写法合成一个控件：点一次回选择菜单。
        command = f"{command} | 人物装配 功法 {entry.content_id} {entry.grade_id}"
    name: object = (
        M.command(M.text(entry.name, tone=_entry_tone(entry.category)), command)
        if has_stable_id
        else entry.name
    )
    parts: list[object] = [name]
    if entry.grade_name:
        parts.extend((" · ", entry.grade_name))
    if entry.category in {"基础物品", "修行资粮", "器藏"} or entry.quantity > 1:
        parts.append(f" × {entry.quantity}")
    if entry.equipped_slots:
        parts.extend((" · 已装", "、".join(entry.equipped_slots)))
    if entry.material_total is not None:
        parts.append(f" · 投入{entry.material_total}份")
    # 装配已并进名字那条分支控件，不再单占一个按钮。
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


def _entry_tone(category: str) -> str:
    return {
        "道藏": "mystic",
        "器藏": "metal",
        "先天灵宝": "cultivation",
    }.get(category, "emphasis")


__all__ = ["category", "error", "home", "page"]
