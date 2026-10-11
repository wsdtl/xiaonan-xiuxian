"""从命令注册表生成协议中立的帮助消息。"""

from __future__ import annotations

from message import DocumentBuilder, Action, DocumentMessage, M

from game.cmd.help_registry import CommandHelpEntry, help_registry

GAME_NAME = "晓楠修仙"


def help_message(query: str = "") -> DocumentMessage:
    normalized = " ".join(str(query or "").split())
    if not normalized:
        return _home_message()
    elif normalized in help_registry.categories():
        return _category_message(normalized)
    elif entry := help_registry.find(normalized):
        return _detail_message(entry)
    return _not_found_message(normalized)


#: 用法里「名称」类槽位——`help` 这一页把它们一律换成「编号」，只讲 id 写法。
_ID_SLOTS = (
    "编号或名称", "名称或编号", "阵法名", "珍物名", "角色名或编号", "宗门名或编号",
    "丹药编号或名称", "丹药编号或丹药名称", "器律编号或名称", "器具编号或名称",
    "功法编号或名称", "编号", "名称", "角色名", "宗门名", "道侣", "品级",
)

#: 一页放多少条——这一页没有按钮，页码靠手打，所以页别太大。
_ID_PAGE_SIZE = 24


def id_form(usage: str) -> str:
    """把用法里的名称类槽位换成「编号」：同一件东西，这一页只讲 id 写法。

    含中文=名字写法、只有数字与冒号=id 写法（《阵法说明》第五节）。
    """

    parts = str(usage or "").split(None, 1)
    if not parts:
        return ""
    head = parts[0]
    tail = parts[1] if len(parts) > 1 else ""
    for slot in sorted(_ID_SLOTS, key=len, reverse=True):
        if slot == "品级":
            continue
        tail = tail.replace(slot, "编号")
    tail = tail.replace("品级", "品级编号")
    return " ".join((head + " " + tail).split())


def id_help_message(page: int = 1) -> DocumentMessage:
    """`help`：按 id 写法罗列命令。不参与「帮助」的分类联动，也不带按钮。"""

    rows: list[tuple[str, str]] = []
    for category in help_registry.categories():
        for entry in help_registry.in_category(category):
            usages = tuple(str(usage) for usage in entry.spec.usage)
            if not usages:
                continue
            picked = next(
                (usage for usage in usages if any(slot in usage for slot in _ID_SLOTS)),
                usages[0],
            )
            rows.append((entry.command, id_form(picked)))
    total = max(1, (len(rows) + _ID_PAGE_SIZE - 1) // _ID_PAGE_SIZE)
    current = min(max(int(page or 1), 1), total)
    builder = (
        M.document()
        .header(GAME_NAME)
        .section("help", icon="system")
        .small("这一页只列 id 写法（只有数字与冒号的那种）；中文写法另外看「帮助」。")
    )
    begin = (current - 1) * _ID_PAGE_SIZE
    for command, usage in rows[begin : begin + _ID_PAGE_SIZE]:
        builder.line(M.text(usage))
    builder.small("第 %d/%d 页，共 %d 条。" % (current, total, len(rows)))
    # help 只带自己的导航：上一页/下一页/返回自己的首页。
    # 刻意不指向中文「帮助」——那是别的组件的联动，不掺和。
    actions: list[Action] = []
    if current > 1:
        actions.append(
            Action(
                "help.id_prev",
                "上一页",
                "help %d" % (current - 1),
                behavior="callback",
                style="secondary",
            )
        )
    if current < total:
        actions.append(
            Action(
                "help.id_next",
                "下一页",
                "help %d" % (current + 1),
                behavior="callback",
            )
        )
    if current > 1:
        actions.append(
            Action(
                "help.id_home",
                "返回首页",
                "help",
                behavior="callback",
                style="secondary",
            )
        )
    if actions:
        builder.actions(tuple(actions))
    return builder.build()


def _home_message() -> DocumentMessage:
    builder = (
        M.document()
        .header(GAME_NAME)
        .section("帮助", icon="system")
        .small("按分类查看当前已经开放的命令。")
    )
    categories = help_registry.categories()
    _category_rows(builder, categories)
    if not categories:
        builder.line(M.status("暂无命令", tone="muted"))
    return builder.build()


def _category_message(category: str) -> DocumentMessage:
    builder = M.document().header(GAME_NAME).section(category, icon="system")
    entries = help_registry.in_category(category)
    for entry in entries:
        builder.line(
            M.command(entry.command, f"帮助 {entry.command}"), " - ", entry.spec.summary
        )
    if not entries:
        builder.line(M.status("暂未开放", tone="muted"))
    return builder.actions((_home_action(),)).build()


def _detail_message(entry: CommandHelpEntry) -> DocumentMessage:
    builder = (
        M.document()
        .header(entry.command)
        .section("说明", icon="guide")
        .line(entry.spec.summary)
    )
    for usage in entry.spec.usage:
        builder.field("发送", usage)
    if entry.aliases:
        builder.field("也可发送", "、".join(entry.aliases))
    if entry.spec.side_effect:
        builder.field("结果", entry.spec.side_effect)
    can_execute_without_arguments = any(
        usage == entry.command for usage in entry.spec.usage
    )
    execute_action = (
        Action("help.execute", "发送命令", entry.command, behavior="callback")
        if can_execute_without_arguments
        else Action(
            "help.fill",
            "填写命令",
            f"{entry.command} ",
            behavior="fill",
            style="secondary",
        )
    )
    return builder.actions(
        (
            execute_action,
            Action(
                "help.category",
                "返回分类",
                f"帮助 {entry.spec.category}",
                behavior="callback",
                style="secondary",
            ),
        )
    ).build()


def _not_found_message(query: str) -> DocumentMessage:
    builder = (
        M.document()
        .header(GAME_NAME)
        .section("没有找到帮助", icon="notice")
        .line(M.status("未找到", tone="warning"), " ", query)
        .section("可用分类")
    )
    _category_rows(builder, help_registry.categories())
    return builder.actions((_home_action(),)).build()


def _category_rows(builder: DocumentBuilder, categories: tuple[str, ...]) -> None:
    for start in range(0, len(categories), 3):
        parts: list[object] = []
        for index, category in enumerate(categories[start : start + 3]):
            if index:
                parts.append("　")
            parts.append(M.command(category, f"帮助 {category}"))
        builder.line(*parts)


def _home_action() -> Action:
    return Action(
        "help.home", "帮助首页", "帮助", behavior="callback", style="secondary"
    )


__all__ = [
    "id_form",
    "id_help_message",
    "_category_message",
    "_detail_message",
    "_home_message",
    "help_message",
]
