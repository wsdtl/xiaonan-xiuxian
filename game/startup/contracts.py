"""统一执行跨命令、跨核心服务的运行时启动检查。"""

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
    sect_war: _StateOwner
    hosting: _StateOwner
    injury: _StateOwner
    innate_treasure: _StateOwner
    raid: _StateOwner
    duel: _StateOwner
    gift: _StateOwner


class StartupContractError(ValueError):
    """运行时组合不满足启动契约。"""


def validate_startup_contracts(core: _CoreServices) -> None:
    """在服务装配完成后一次校验全部跨模块运行契约。"""

    from game.cmd.command import registered_command_routes, registered_guard_rules

    validate_command_uniqueness(registered_command_routes())
    owners = {
        "player_state": core.player_state.state_types,
        "companion": core.companion.state_types,
        "character": core.character.state_types,
        "asset": core.asset.state_types,
        "exploration": core.exploration.state_types,
        "retreat": core.retreat.state_types,
        "gathering": core.gathering.state_types,
        "team": core.team.state_types,
        "sect": core.sect.state_types,
        "formation": core.formation.state_types,
        "hosting": core.hosting.state_types,
        "injury": core.injury.state_types,
        "innate_treasure": core.innate_treasure.state_types,
        "raid": core.raid.state_types,
        "duel": core.duel.state_types,
        "gift": core.gift.state_types,
    }
    sect_war = getattr(core, "sect_war", None)
    if sect_war is not None:
        owners["sect_war"] = sect_war.state_types
    validate_state_type_ownership(owners)
    for rule_name in registered_guard_rules():
        core.player_state.validate_guard_rule(rule_name)


def validate_command_uniqueness(
    commands: Iterable[tuple[str, str, str]],
) -> tuple[tuple[str, str, str], ...]:
    """拒绝由不同组件注册的同名命令。"""

    entries = tuple(commands)
    seen: dict[str, tuple[str, str, str]] = {}
    duplicates: list[str] = []
    for command, scope, module in entries:
        key = command.casefold()
        previous = seen.get(key)
        if previous is not None:
            duplicates.append(
                f"{command} ({previous[1]}，{previous[2]} / {scope}，{module})"
            )
        else:
            seen[key] = (command, scope, module)
    if duplicates:
        raise StartupContractError("游戏命令重复注册：\n" + "\n".join(duplicates))
    return entries


def validate_state_type_ownership(
    owners: Mapping[str, Iterable[str]],
) -> dict[str, str]:
    """确认每种数据库状态只由一个核心服务持有写权限。"""

    ownership: dict[str, str] = {}
    for owner, state_types in owners.items():
        for raw_state_type in state_types:
            state_type = str(raw_state_type or "").strip()
            if not state_type:
                raise StartupContractError(f"核心服务 {owner} 声明了空状态类型")
            existing = ownership.get(state_type)
            if existing is not None:
                raise StartupContractError(
                    f"数据库状态类型归属重复：{state_type} -> {existing}、{owner}"
                )
            ownership[state_type] = owner
    return ownership


__all__ = [
    "StartupContractError",
    "validate_command_uniqueness",
    "validate_startup_contracts",
    "validate_state_type_ownership",
]
