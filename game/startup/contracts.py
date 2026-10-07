"""跨服务启动契约：命令注册表自洽。

只保留两条最基础、最核心的检查：

1. 命令不能重复注册（同一命令注册两次，玩家命令直接错乱）；
2. 每个命令声明的守卫规则必须真实存在（注册表悬空同样是硬伤）。

状态类型归属校验已移除：它的全部成本是维护一份跨服务名清单，而真正出错时
数据库按 `state_type` 定位会立刻暴露，不需要在启动期再核一遍。
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol


class _GuardOwner(Protocol):
    def validate_guard_rule(self, rule_name: str) -> None: ...


class StartupContractError(ValueError):
    """运行时组合不满足启动契约。"""


def validate_startup_contracts(player_state: _GuardOwner) -> None:
    from game.cmd.command import registered_command_routes, registered_guard_rules

    validate_command_uniqueness(registered_command_routes())
    for rule_name in registered_guard_rules():
        player_state.validate_guard_rule(rule_name)


def validate_command_uniqueness(
    commands: Iterable[tuple[str, str, str]],
) -> tuple[tuple[str, str, str], ...]:
    entries = tuple(commands)
    seen: dict[str, tuple[str, str, str]] = {}
    duplicates: list[str] = []
    for command, scope, module in entries:
        key = command.casefold()
        if key in seen:
            previous = seen[key]
            duplicates.append(f"{command} ({previous[1]}，{previous[2]} / {scope}，{module})")
        else:
            seen[key] = (command, scope, module)
    if duplicates:
        raise StartupContractError("游戏命令重复注册：\n" + "\n".join(duplicates))
    return entries


__all__ = ["StartupContractError", "validate_command_uniqueness", "validate_startup_contracts"]
