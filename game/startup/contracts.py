"""统一执行跨命令、跨核心服务的运行时启动检查。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol


class _StateOwner(Protocol):
    @property
    def state_types(self) -> Iterable[str]: ...


class _PlayerStateOwner(_StateOwner, Protocol):
    def validate_guard_rule(self, rule_name: str) -> None: ...


class _JsonDataOwner(Protocol):
    def entities(self, section: str) -> Mapping[str, Mapping[str, object]]: ...

    def entity_record(self, section: str, entity_id: str) -> object: ...


class _CoreServices(Protocol):
    data: _JsonDataOwner
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
    validate_construct_term_slots(core.data)
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


_CONSTRUCT_SECTIONS = ("功法", "真意", "气机", "器律")
def validate_construct_term_slots(data: _JsonDataOwner) -> None:
    """只校核运行时必须成立的构筑词条类别和槽位引用。

    槽位只在当前构筑内解析；没有 ``词条`` 表的旧构筑保持原契约，
    但一旦声明词条表，所有引用必须命中本表。
    词条可见名称已经在内容整理阶段确认，不在每次启动重复扫描。
    """

    from game.core.combat.build_terms import SLOT_KEYS, TERM_CATEGORIES

    for section in _CONSTRUCT_SECTIONS:
        for entity_id, entity in data.entities(section).items():
            table = entity.get("词条") if isinstance(entity, Mapping) else None
            if table is None:
                continue
            if not isinstance(table, Mapping):
                raise StartupContractError(f"{section} {entity_id} 的词条必须是对象")
            source_file = str(
                getattr(data.entity_record(section, entity_id), "source_file", "")
                or "<未知文件>"
            )
            owner = f"{section} {entity_id} -> {source_file}"
            unknown_categories = set(table) - set(TERM_CATEGORIES)
            if unknown_categories:
                raise StartupContractError(
                    f"{owner} 的词条类别未知：{ '、'.join(sorted(map(str, unknown_categories))) }"
                )
            for category in TERM_CATEGORIES:
                category_table = table.get(category, {})
                if not isinstance(category_table, Mapping):
                    raise StartupContractError(f"{owner} 的词条.{category} 必须是对象")
                for slot, raw_term in category_table.items():
                    slot = str(slot).strip()
                    if not slot or not isinstance(raw_term, Mapping):
                        raise StartupContractError(
                            f"{owner} 的词条.{category} 槽位定义无效：{slot or '<空>'}"
                        )
                    if not str(raw_term.get("名称") or "").strip():
                        raise StartupContractError(
                            f"{owner} 的词条.{category}.{slot} 缺少名称"
                        )
            _validate_slot_references(
                entity,
                owner=owner,
                table=table,
                slot_keys=SLOT_KEYS,
            )
def _validate_slot_references(
    value: object,
    *,
    owner: str,
    table: Mapping[str, object],
    slot_keys: Mapping[str, str],
    path: tuple[str, ...] = (),
) -> None:
    if isinstance(value, Mapping):
        if path and path[0] == "词条":
            return
        for key, child in value.items():
            category = slot_keys.get(str(key))
            if category is not None:
                slot = str(child or "").strip()
                category_table = table.get(category)
                if not isinstance(category_table, Mapping) or slot not in category_table:
                    dotted = ".".join((*path, str(key)))
                    raise StartupContractError(
                        f"{owner} 的槽位引用未定义：{dotted} -> {category}.{slot or '<空>'}"
                    )
            _validate_slot_references(
                child,
                owner=owner,
                table=table,
                slot_keys=slot_keys,
                path=(*path, str(key)),
            )
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _validate_slot_references(
                child,
                owner=owner,
                table=table,
                slot_keys=slot_keys,
                path=(*path, f"[{index}]"),
            )


__all__ = [
    "StartupContractError",
    "validate_construct_term_slots",
    "validate_command_uniqueness",
    "validate_startup_contracts",
    "validate_state_type_ownership",
]
