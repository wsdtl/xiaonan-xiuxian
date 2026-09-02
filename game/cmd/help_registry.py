"""游戏命令帮助元数据与只读注册表。"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

HELP_CATEGORY_ORDER = (
    "角色",
    "道侣",
    "修行",
    "行动",
    "世界",
    "战斗",
    "炼制",
    "资源",
)


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


@dataclass(frozen=True)
class HelpSpec:
    """一条玩家可见命令的最小公开说明。"""

    category: str
    summary: str
    usage: tuple[str, ...]
    side_effect: str = ""
    order: int = 100

    def __post_init__(self) -> None:
        category = _text(self.category)
        summary = _text(self.summary)
        usage = tuple(value for raw in self.usage if (value := _text(raw)))
        side_effect = _text(self.side_effect)
        if category not in HELP_CATEGORY_ORDER:
            raise ValueError(f"未知帮助分类：{self.category}")
        if not summary:
            raise ValueError("命令帮助缺少一句话用途")
        if not usage:
            raise ValueError("命令帮助至少需要一种写法")
        if isinstance(self.order, bool) or int(self.order) < 0:
            raise ValueError("命令帮助顺序不能小于零")
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "usage", usage)
        object.__setattr__(self, "side_effect", side_effect)
        object.__setattr__(self, "order", int(self.order))


@dataclass(frozen=True)
class CommandHelpEntry:
    command: str
    aliases: tuple[str, ...]
    spec: HelpSpec
    source_module: str = ""


class HelpRegistry:
    """收集命令注册时声明的帮助，不保存玩家状态。"""

    def __init__(self) -> None:
        self._entries: dict[str, CommandHelpEntry] = {}
        self._commands: dict[str, str] = {}

    def register(
        self,
        commands: str | Sequence[str],
        spec: HelpSpec,
        *,
        source_module: str = "",
    ) -> CommandHelpEntry:
        normalized = _commands(commands)
        primary = normalized[0]
        owner = _text(source_module)
        entry = CommandHelpEntry(primary, normalized[1:], spec, owner)
        existing = self._entries.get(primary)
        if existing is not None:
            if existing.source_module != owner:
                raise ValueError(f"命令帮助重复且定义不一致：{primary}")
            self._remove_entry(primary)
        for command in normalized:
            owner = self._commands.get(command.casefold())
            if owner is not None:
                raise ValueError(f"帮助命令或别名重复：{command} -> {owner}")
        self._entries[primary] = entry
        for command in normalized:
            self._commands[command.casefold()] = primary
        return entry

    def _remove_entry(self, primary: str) -> None:
        """替换同一主命令时移除旧索引。"""

        entry = self._entries.pop(primary, None)
        if entry is None:
            return
        for command in (entry.command, *entry.aliases):
            self._commands.pop(command.casefold(), None)

    def find(self, command: object) -> CommandHelpEntry | None:
        primary = self._commands.get(_text(command).casefold())
        return self._entries.get(primary) if primary is not None else None

    def categories(self) -> tuple[str, ...]:
        populated = {entry.spec.category for entry in self._entries.values()}
        return tuple(
            category for category in HELP_CATEGORY_ORDER if category in populated
        )

    def in_category(self, category: object) -> tuple[CommandHelpEntry, ...]:
        normalized = _text(category)
        return tuple(
            sorted(
                (
                    entry
                    for entry in self._entries.values()
                    if entry.spec.category == normalized
                ),
                key=lambda entry: (entry.spec.order, entry.command),
            )
        )

    def entries(self) -> tuple[CommandHelpEntry, ...]:
        category_order = {
            category: index for index, category in enumerate(HELP_CATEGORY_ORDER)
        }
        return tuple(
            sorted(
                self._entries.values(),
                key=lambda entry: (
                    category_order[entry.spec.category],
                    entry.spec.order,
                    entry.command,
                ),
            )
        )


def _commands(commands: str | Sequence[str]) -> tuple[str, ...]:
    values: Iterable[object] = (commands,) if isinstance(commands, str) else commands
    normalized = tuple(command for raw in values if (command := _text(raw)))
    if not normalized:
        raise ValueError("命令帮助只能绑定显式命令")
    if len(normalized) != len({command.casefold() for command in normalized}):
        raise ValueError("同一命令帮助中不能重复声明命令或别名")
    return normalized


help_registry = HelpRegistry()


__all__ = [
    "HELP_CATEGORY_ORDER",
    "CommandHelpEntry",
    "HelpRegistry",
    "HelpSpec",
    "help_registry",
]
