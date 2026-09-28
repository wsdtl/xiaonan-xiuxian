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
    "_category_message",
    "_detail_message",
    "_home_message",
    "help_message",
]
