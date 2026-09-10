"""跨服务启动契约；构筑词条由战斗装配显式绑定。"""
from __future__ import annotations
from collections.abc import Iterable, Mapping
from typing import Protocol

class _StateOwner(Protocol):
    @property
    def state_types(self) -> Iterable[str]: ...
class _PlayerStateOwner(_StateOwner, Protocol):
    def validate_guard_rule(self, rule_name: str) -> None: ...
class _CoreServices(Protocol):
    player_state: _PlayerStateOwner
    companion: _StateOwner
    character: _StateOwner
    asset: _StateOwner
    exploration: _StateOwner
    retreat: _StateOwner
    gathering: _StateOwner
    team: _StateOwner
    sect: _StateOwner
    formation: _StateOwner
    hosting: _StateOwner
    injury: _StateOwner
    innate_treasure: _StateOwner
    raid: _StateOwner
    duel: _StateOwner
    gift: _StateOwner

class StartupContractError(ValueError):
    """运行时组合不满足启动契约。"""

def validate_startup_contracts(core: _CoreServices) -> None:
    from game.cmd.command import registered_command_routes, registered_guard_rules
    validate_command_uniqueness(registered_command_routes())
    owners = {name: getattr(core, name).state_types for name in (
        "player_state", "companion", "character", "asset", "exploration", "retreat",
        "gathering", "team", "sect", "formation", "hosting", "injury",
        "innate_treasure", "raid", "duel", "gift")}
    sect_war = getattr(core, "sect_war", None)
    if sect_war is not None:
        owners["sect_war"] = sect_war.state_types
    validate_state_type_ownership(owners)
    for rule_name in registered_guard_rules():
        core.player_state.validate_guard_rule(rule_name)

def validate_command_uniqueness(commands: Iterable[tuple[str, str, str]]) -> tuple[tuple[str, str, str], ...]:
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

def validate_state_type_ownership(owners: Mapping[str, Iterable[str]]) -> dict[str, str]:
    ownership: dict[str, str] = {}
    for owner, state_types in owners.items():
        for raw_state_type in state_types:
            state_type = str(raw_state_type or "").strip()
            if not state_type:
                raise StartupContractError(f"核心服务 {owner} 声明了空状态类型")
            if state_type in ownership:
                raise StartupContractError(f"数据库状态类型归属重复：{state_type} -> {ownership[state_type]}、{owner}")
            ownership[state_type] = owner
    return ownership

__all__ = ["StartupContractError", "validate_command_uniqueness", "validate_startup_contracts", "validate_state_type_ownership"]
