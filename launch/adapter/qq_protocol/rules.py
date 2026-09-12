"""QQ 驱动器自己的文本命令规则与匹配索引。"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from re import Pattern
from typing import Any

TextCommands = str | list[str] | tuple[str, ...]
RegexCommands = Pattern | list[Pattern] | tuple[Pattern, ...]


@dataclass(frozen=True)
class QqCommandRule:
    """一条 QQ 命令注册规则。"""

    func: Callable
    priority: int
    block: bool
    order: int
    pattern: Pattern | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QqCommandMatch:
    """QQ 消息命中命令后的驱动器内部结果。"""

    rule: QqCommandRule
    command: str
    message: str
    match: re.Match | None = None


class QqCommandRegistry:
    """维护 QQ 自己的命令注册、索引和匹配顺序。"""

    def __init__(self) -> None:
        self.command_rules: dict[str, list[QqCommandRule]] = {}
        self.fullmatch_rules: dict[str, list[QqCommandRule]] = {}
        self.regex_rules: dict[str, list[QqCommandRule]] = {}
        self.regex_fallback: list[QqCommandRule] = []
        self.regex_prefix_lengths: set[int] = set()
        self._register_order = 0

    @property
    def command_count(self) -> int:
        return len(self.command_rules)

    @property
    def fullmatch_count(self) -> int:
        return len(self.fullmatch_rules)

    @property
    def regex_rule_count(self) -> int:
        return sum(len(rules) for rules in self.regex_rules.values()) + len(
            self.regex_fallback
        )

    def build_index(self) -> None:
        """整理固定前缀索引和稳定执行顺序。"""

        self.regex_prefix_lengths = {len(prefix) for prefix in self.regex_rules}
        for rule_group in (
            self.command_rules.values(),
            self.fullmatch_rules.values(),
            self.regex_rules.values(),
        ):
            for rules in rule_group:
                rules.sort(key=_rule_order)
        self.regex_fallback.sort(key=_rule_order)

    def match(self, raw_message: str) -> list[QqCommandMatch]:
        """按 QQ 消息正文匹配当前驱动器注册的命令。"""

        command_text = raw_message.strip()
        if not command_text:
            return []

        matched = [
            QqCommandMatch(rule=rule, command=command_text, message="")
            for rule in self.fullmatch_rules.get(command_text, [])
        ]
        command, message = _split_command(command_text)
        matched.extend(
            QqCommandMatch(rule=rule, command=command, message=message)
            for rule in self.command_rules.get(command, [])
        )
        matched.extend(
            QqCommandMatch(
                rule=rule,
                command=command_text,
                message="",
                match=match,
            )
            for rule, match in self._match_regex(command_text)
        )
        matched.sort(key=lambda item: _rule_order(item.rule))
        return matched

    def register_command(
        self,
        cmd: str,
        func: Callable,
        priority: int,
        block: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        command = cmd.strip()
        if not command or any(char.isspace() for char in command):
            raise ValueError("command 注册器需要一个不含空白的命令词")
        self._replace_rule(
            self.command_rules,
            command,
            self._make_rule(func, priority, block, metadata=metadata),
        )

    def register_fullmatch(
        self,
        cmd: str,
        func: Callable,
        priority: int,
        block: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        command = cmd.strip()
        if not command:
            raise ValueError("fullmatch 注册器不接受空命令")
        self._replace_rule(
            self.fullmatch_rules,
            command,
            self._make_rule(func, priority, block, metadata=metadata),
        )

    def register_regex(
        self,
        pattern: Pattern,
        func: Callable,
        priority: int,
        block: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        prefix = _extract_literal_prefix(pattern.pattern)
        rule = self._make_rule(
            func,
            priority,
            block,
            pattern=pattern,
            metadata=metadata,
        )
        if prefix:
            self._replace_rule(self.regex_rules, prefix.casefold(), rule)
        else:
            self.regex_fallback = self._replace_owned(self.regex_fallback, rule)

    @staticmethod
    def _replace_rule(
        registry: dict[str, list[QqCommandRule]],
        key: str,
        rule: QqCommandRule,
    ) -> None:
        registry[key] = QqCommandRegistry._replace_owned(registry.get(key, []), rule)

    @staticmethod
    def _replace_owned(
        rules: list[QqCommandRule], rule: QqCommandRule
    ) -> list[QqCommandRule]:
        owner = rule.func.__module__
        return [value for value in rules if value.func.__module__ != owner] + [rule]

    def _make_rule(
        self,
        func: Callable,
        priority: int,
        block: bool,
        *,
        pattern: Pattern | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> QqCommandRule:
        rule = QqCommandRule(
            func=func,
            priority=priority,
            block=block,
            order=self._register_order,
            pattern=pattern,
            metadata=dict(metadata or {}),
        )
        self._register_order += 1
        return rule

    def _match_regex(self, command: str) -> list[tuple[QqCommandRule, re.Match]]:
        matched: list[tuple[QqCommandRule, re.Match]] = []
        key = command.casefold()
        seen_rules: set[int] = set()

        for length in self.regex_prefix_lengths:
            for rule in self.regex_rules.get(key[:length], []):
                _append_regex_match(matched, seen_rules, rule, command)
        for rule in self.regex_fallback:
            _append_regex_match(matched, seen_rules, rule, command)
        return matched


def normalize_text_commands(value: TextCommands) -> list[str]:
    """按声明顺序整理字符串命令。"""

    commands = list(value) if isinstance(value, (list, tuple)) else [value]
    if any(not isinstance(command, str) for command in commands):
        raise TypeError("fullmatch 和 command 注册器只支持字符串命令")
    return commands


def normalize_regex_commands(value: RegexCommands) -> list[Pattern]:
    """按声明顺序整理正则命令。"""

    commands = list(value) if isinstance(value, (list, tuple)) else [value]
    if any(not isinstance(command, re.Pattern) for command in commands):
        raise TypeError("regex 注册器只支持 re.Pattern")
    return commands


def _append_regex_match(
    matched: list[tuple[QqCommandRule, re.Match]],
    seen_rules: set[int],
    rule: QqCommandRule,
    command: str,
) -> None:
    rule_id = id(rule)
    if rule_id in seen_rules:
        return
    seen_rules.add(rule_id)
    if rule.pattern is None:
        return
    match = rule.pattern.fullmatch(command)
    if match:
        matched.append((rule, match))


def _rule_order(rule: QqCommandRule) -> tuple[int, int]:
    return -rule.priority, rule.order


def _split_command(raw_message: str) -> tuple[str, str]:
    parts = raw_message.split(maxsplit=1)
    if len(parts) == 1:
        return raw_message, ""
    return parts[0], parts[1].strip()


def _extract_literal_prefix(source: str) -> str:
    index = 1 if source.startswith("^") else 0
    prefix: list[str] = []
    metacharacters = set(".^$*+?{}[]|()")

    while index < len(source):
        char = source[index]
        if char in metacharacters:
            break
        if char == "\\":
            if index + 1 >= len(source):
                break
            next_char = source[index + 1]
            if next_char in "AbBdDsSwWZ0123456789":
                break
            prefix.append(next_char)
            index += 2
            continue
        prefix.append(char)
        index += 1
    return "".join(prefix)


__all__ = [
    "QqCommandMatch",
    "QqCommandRegistry",
    "RegexCommands",
    "TextCommands",
    "normalize_regex_commands",
    "normalize_text_commands",
]
