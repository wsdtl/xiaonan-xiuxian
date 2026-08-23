from __future__ import annotations

from types import SimpleNamespace

import pytest

import game.app as game_app
from game.cmd import access_guard, command
from game.config import GameConfig, GameDatabaseConfig
from game.startup import (
    StartupContractError,
    validate_command_uniqueness,
    validate_state_type_ownership,
)


class _FakeDatabase:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _BrokenPlayerState:
    state_types: tuple[str, ...] = ("player_state",)

    def validate_guard_rule(self, rule_name: str) -> None:
        raise RuntimeError(f"未知规则：{rule_name}")


class _StateOwner:
    def __init__(self, *state_types: str) -> None:
        self.state_types = state_types


def test_failed_guard_validation_releases_built_services(monkeypatch) -> None:
    database = _FakeDatabase()
    services = SimpleNamespace(
        core=SimpleNamespace(
            database=database,
            player_state=_BrokenPlayerState(),
            companion=_StateOwner("companion"),
            character=_StateOwner("character", "weapon"),
            asset=_StateOwner("inventory"),
            exploration=_StateOwner(
                "exploration_session",
                "exploration_battle",
                "exploration_latest",
                "exploration_settlement",
            ),
            retreat=_StateOwner(
                "retreat_session",
                "retreat_latest",
                "retreat_settlement",
            ),
            gathering=_StateOwner(
                "gathering_session",
                "gathering_latest",
                "gathering_settlement",
            ),
            team=_StateOwner("team", "team_invite"),
            sect=_StateOwner("sect_invite"),
            formation=_StateOwner("prepared_formation"),
            hosting=_StateOwner("hosting_latest"),
            injury=_StateOwner("injury"),
            innate_treasure=_StateOwner("innate_treasure"),
            raid=_StateOwner("raid_session", "raid_battle", "raid_settlement"),
            duel=_StateOwner("duel_challenge"),
            gift=_StateOwner("gift_transaction"),
        )
    )
    monkeypatch.setattr(game_app, "_services", None)
    monkeypatch.setattr(game_app, "build_game_services", lambda: services)
    monkeypatch.setattr(command, "registered_guard_rules", lambda: ("不存在",))
    monkeypatch.setattr(access_guard, "unregister_game_access_guard", lambda: None)

    with pytest.raises(RuntimeError, match="未知规则"):
        game_app.initialize_game_services()

    assert database.closed is True
    assert game_app._services is None


def test_real_composition_root_builds_location_and_position_services(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        game_app,
        "game_config",
        GameConfig(
            GameDatabaseConfig(
                tmp_path / "game.db",
                tmp_path / "runtime.db",
                5000,
            )
        ),
    )

    services = game_app.build_game_services()

    assert services.core.location.status().initialized is True
    assert services.core.companion.status().companion_count == 264
    assert services.core.team.status().maximum_players == 3
    assert services.core.retreat.status().maximum_rounds == 6
    assert len(services.core.gathering.status().modes) == 2
    assert services.features.weizhi is not None
    assert services.features.duiwu is not None
    assert services.features.biguan is not None
    assert services.features.caiyao is not None
    assert services.features.caikuang is not None
    services.core.database.close()


def test_state_type_ownership_rejects_cross_service_collisions() -> None:
    assert validate_state_type_ownership(
        {
            "character": {"character", "weapon"},
            "asset": {"inventory"},
        }
    ) == {
        "character": "character",
        "weapon": "character",
        "inventory": "asset",
    }
    with pytest.raises(ValueError, match="归属重复"):
        validate_state_type_ownership(
            {
                "character": {"character"},
                "other": {"character"},
            }
        )


def test_command_uniqueness_rejects_cross_component_collisions() -> None:
    commands = (
        ("位置", "通用", "game.cmd.通用.位置"),
        ("位置", "专属", "game.cmd.专属.测试"),
    )

    with pytest.raises(StartupContractError, match="命令重复注册"):
        validate_command_uniqueness(commands)
