"""从命令注册表生成协议中立的帮助消息。"""

from __future__ import annotations

from collections.abc import Callable

from message import DocumentBuilder, Action, DocumentMessage, M

from game.cmd.help_registry import CommandHelpEntry, help_registry

from launch.paths import public_url

GAME_NAME = "晓楠修仙"


def help_message(
    query: str = "",
    *,
    id_converter: Callable[[str], str] | None = None,
    nav: str = "帮助",
) -> DocumentMessage:
    """帮助页。`id_converter` 给定时，把**命令写法**里的中文名与品级换成编号。

    「帮助」是给人看的（不给转换器）；`help` 是给机器/脚本看的纯 id 写法（给转换器）。
    """

    normalized = " ".join(str(query or "").split())
    if not normalized:
        return _home_message(id_converter=id_converter, nav=nav)
    elif normalized in help_registry.categories():
        return _category_message(normalized, id_converter=id_converter, nav=nav)
    elif entry := help_registry.find(normalized):
        return _detail_message(entry, id_converter=id_converter, nav=nav)
    return _not_found_message(normalized, id_converter=id_converter, nav=nav)


def _shown(text: str, id_converter: object) -> str:
    """给定时把中文名换成编号；命令词（第一个词）不动。"""

    if id_converter is None:
        return str(text)
    parts = str(text).split(None, 1)
    if not parts:
        return ""
    head = parts[0]
    tail = parts[1] if len(parts) > 1 else ""
    return (head + " " + id_converter(tail)).strip() if tail else head


def _home_message(*, id_converter=None, nav: str = "帮助") -> DocumentMessage:
    builder = (
        M.document()

        .section("帮助", icon="system")
        .small("按分类查看当前已经开放的命令。")
    )
    builder.line(M.link("游戏介绍与玩法", public_url("info")))
    categories = help_registry.categories()
    _category_rows(builder, categories, nav=nav)
    if not categories:
        builder.line(M.status("暂无命令", tone="muted"))
    return builder.build()


def _usage_rows(
    builder: DocumentBuilder, entries: object, *, nav: str, id_converter: object
) -> None:
    """把命令按行铺开：「帮助」与 `help` 共用这一份。"""

    for entry in entries:
        # 摘要保持原样：「帮助」与 `help` 的内容一模一样，id 化只落在命令写法上。
        builder.line(
            M.command(entry.command, f"{nav} {entry.command}"),
            " - ",
            entry.spec.summary,
        )


def _category_message(category: str, *, id_converter=None, nav: str = "帮助") -> DocumentMessage:
    builder = M.document().header(GAME_NAME).section(category, icon="system")
    entries = help_registry.in_category(category)
    _usage_rows(builder, entries, nav=nav, id_converter=id_converter)
    if not entries:
        builder.line(M.status("暂未开放", tone="muted"))
    return builder.actions((_home_action(nav),)).build()


def _detail_message(entry: CommandHelpEntry, *, id_converter=None, nav: str = "帮助") -> DocumentMessage:
    builder = (
        M.document()
        .header(entry.command)
        .section("说明", icon="guide")
        .line(entry.spec.summary)
    )
    for usage in entry.spec.usage:
        # 裸用法交给底部「发送命令」按钮，正文里再放一条就是联动与按钮重复（build 会拒绝）。
        if usage == entry.command:
            continue
        # 可点击但不直接发：点一下只把命令填进输入框，玩家自己补参数或改。
        label = _shown(usage, id_converter)
        builder.line(M.command(label, label))
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
                f"{nav} {entry.spec.category}",
                behavior="callback",
                style="secondary",
            ),
        )
    ).build()


def _not_found_message(query: str, *, id_converter=None, nav: str = "帮助") -> DocumentMessage:
    builder = (
        M.document()

        .section("没有找到帮助", icon="notice")
        .line(M.status("未找到", tone="warning"), " ", query)
        .section("可用分类")
    )
    _category_rows(builder, help_registry.categories())
    return builder.actions((_home_action(),)).build()


def _category_rows(builder: DocumentBuilder, categories: tuple[str, ...], *, nav: str = "帮助") -> None:
    for start in range(0, len(categories), 3):
        parts: list[object] = []
        for index, category in enumerate(categories[start : start + 3]):
            if index:
                parts.append("　")
            parts.append(M.command(category, f"{nav} {category}"))
        builder.line(*parts)


def _home_action(nav: str = "帮助") -> Action:
    return Action(
        "help.home", f"{nav}首页", nav, behavior="callback", style="secondary"
    )


__all__ = [
    "help_message",
]
