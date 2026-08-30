from __future__ import annotations

import asyncio
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest

from game.core.asset import AssetService
from game.core.character import CharacterService
from game.core.data import JsonDataService
from game.core.database import DatabaseService, StateAddress
from game.core.forging import ForgingService
from game.core.growth import GrowthService
from game.core.injury import InjuryService
from game.core.location import (
    LocationConflictError,
    LocationMoveCommand,
    LocationService,
)
from game.core.player_state import PlayerStateService
from game.core.pool import PoolService
from game.core.world import WorldService
from game.features.chakan_juese import (
    CharacterOverviewFeature,
    CharacterOverviewMissingError,
)
from game.features.chuangjian_renwu import (
    CharacterExistsError,
    CreateCharacterFeature,
    CreateCharacterRequest,
    InvalidCreateCharacterError,
)
from message import DocumentMessage
from message.renderers.plain_text import render_plain_text
from tests.support import innate_treasure_service


def _run(awaitable):
    return asyncio.run(awaitable)


class _HostingStub:
    def status(self):
        return SimpleNamespace(initialized=True)

    async def current(self, _user_id: str):
        return None


def _features(
    tmp_path: Path,
) -> tuple[
    CreateCharacterFeature,
    CharacterOverviewFeature,
    CharacterService,
    LocationService,
    DatabaseService,
]:
    root = Path(__file__).resolve().parents[2]
    data = JsonDataService(root / "data")
    data.initialize()
    pool = PoolService(data)
    pool.initialize()
    growth = GrowthService(data, pool)
    growth.initialize()
    database = DatabaseService(tmp_path / "game.db")
    database.initialize()
    world = WorldService(data)
    world.initialize()
    player_state = PlayerStateService(data, database)
    player_state.initialize()
    location = LocationService(data, database, world)
    location.initialize()
    asset = AssetService(data, database)
    asset.initialize()
    forging = ForgingService(
        data, database, asset, world, location, innate_treasure_service(data, database)
    )
    forging.initialize()
    character = CharacterService(
        data, database, player_state, location, asset, growth, forging
    )
    character.initialize()
    injury = InjuryService(data, database)
    injury.initialize()
    feature = CreateCharacterFeature(data, world, character)
    feature.initialize()
    overview = CharacterOverviewFeature(
        character,
        player_state,
        world,
        location,
        injury,
        innate_treasure_service(data, database),
        _HostingStub(),
    )
    overview.initialize()
    return feature, overview, character, location, database


def test_create_character_commits_all_initial_states(tmp_path: Path) -> None:
    feature, _, _, location, database = _features(tmp_path)

    result = _run(
        feature.create(CreateCharacterRequest("qq-1", "event-1", "林远", "男"))
    )

    assert result.realm_id == "510001"
    assert result.location_name == "溪隐台"
    assert result.initial_items == (("小还丹", "黄品", 3), ("养神丹", "黄品", 2))
    snapshots = _run(database.list_for_user("qq-1"))
    assert {
        (item.address.state_type, item.address.state_key) for item in snapshots
    } == {
        ("character", "main"),
        ("cultivation", "main"),
        ("weapon", "main"),
        ("player_state", "main"),
        ("inventory", "100002:01"),
        ("inventory", "100005:01"),
    }
    character = _run(database.get(StateAddress("qq-1", "character", "main")))
    assert character is not None
    assert "位置" not in character.value
    assert "状态" not in character.value
    assert _run(location.current("qq-1")).xy == (15, 17)


def test_same_create_request_is_idempotent(tmp_path: Path) -> None:
    feature, _, _, _, database = _features(tmp_path)
    request = CreateCharacterRequest("qq-1", "event-1", "林远", "男")

    first = _run(feature.create(request))
    second = _run(feature.create(request))

    assert first.replayed is False
    assert second.replayed is True
    assert database.status().transaction_count == 1


def test_existing_character_rejects_new_create_request(tmp_path: Path) -> None:
    feature, _, _, _, _ = _features(tmp_path)
    _run(feature.create(CreateCharacterRequest("qq-1", "event-1", "林远", "男")))

    with pytest.raises(CharacterExistsError):
        _run(feature.create(CreateCharacterRequest("qq-1", "event-2", "白芷", "女")))


def test_invalid_input_has_no_database_side_effect(tmp_path: Path) -> None:
    feature, _, _, _, database = _features(tmp_path)

    with pytest.raises(InvalidCreateCharacterError):
        _run(feature.create(CreateCharacterRequest("qq-1", "event-1", "A", "男")))

    assert _run(database.list_for_user("qq-1")) == ()
    assert _run(database.get_location("qq-1")) is None


def test_character_overview_combines_owned_service_results(
    tmp_path: Path, monkeypatch
) -> None:
    create, overview, _, _, _ = _features(tmp_path)
    _run(create.create(CreateCharacterRequest("qq-1", "event-1", "林远", "男")))

    result = _run(overview.inspect("qq-1"))
    character = result.character

    assert (character.name, character.gender) == ("林远", "男")
    assert (character.realm_name, character.level) == ("灵动", 1)
    assert result.xy == (15, 17)
    assert dict(character.attributes)["攻击"] == 5
    assert dict(character.resources) == {"血气": 100, "精神": 100, "护盾": 0}
    assert character.sect_contribution == 0
    assert character.cultivation_slots == (("功法", 6), ("真意", 6), ("气机", 6))
    assert result.cultivation_usage == (
        ("功法", 0, 6),
        ("真意", 0, 6),
        ("气机", 0, 6),
    )
    assert result.innate_treasure_usage == (0, 1)
    assert character.equipped_content == ()
    assert character.weapon.stage == "凡器"
    assert character.weapon.attack == 10
    assert character.weapon.open_law_slots == 0
    assert character.inventory.stack_count == 2
    assert character.inventory.total_quantity == 5
    assert result.location_name == "溪隐台"
    assert result.states == (("行为", "空闲"), ("队伍", "未组队"), ("控制", "自主"))

    class RecordingManager:
        message: DocumentMessage | None = None

        async def send(self, message: DocumentMessage) -> None:
            self.message = message

    class OverviewStub:
        async def inspect(self, user_id: str):
            assert user_id == "qq-1"
            return result

    command_module = import_module("game.cmd.通用.角色")
    monkeypatch.setattr(
        command_module,
        "current_game_services",
        lambda: SimpleNamespace(features=SimpleNamespace(chakan_juese=OverviewStub())),
    )
    manager = RecordingManager()
    _run(command_module.show_character(user_id="qq-1", manager=manager))

    assert manager.message is not None
    content = render_plain_text(manager.message.document)
    assert "林远" in content
    assert "灵动" in content
    assert "溪隐台" in content
    assert "功法: 0/6" in content
    assert "先天灵宝" in content
    assert "先天灵宝: 未执掌" in content
    assert "无名器胚" in content
    assert "攻击: 10" in content
    assert "宗门贡献: 0" in content


def test_character_overview_rejects_missing_character(tmp_path: Path) -> None:
    _, overview, _, _, _ = _features(tmp_path)

    with pytest.raises(CharacterOverviewMissingError):
        _run(overview.inspect("qq-1"))


def test_location_move_updates_only_position_with_optimistic_version(
    tmp_path: Path,
) -> None:
    create, _, _, location, database = _features(tmp_path)
    _run(create.create(CreateCharacterRequest("qq-1", "event-1", "林远", "男")))
    moved = _run(
        location.move(LocationMoveCommand("qq-1", "travel-1", (15, 17), (16, 17)))
    )
    snapshot = _run(database.get(StateAddress("qq-1", "character", "main")))
    position = _run(database.get_location("qq-1"))

    assert moved.changed is True
    assert moved.destination_xy == (16, 17)
    assert snapshot is not None
    assert "位置" not in snapshot.value
    assert snapshot.version == 1
    assert position is not None and position.xy == (16, 17)
    assert position.version == 2

    unchanged = _run(
        location.move(LocationMoveCommand("qq-1", "travel-2", (16, 17), (16, 17)))
    )
    assert unchanged.changed is False
    assert database.status().transaction_count == 2


def test_location_move_rejects_stale_origin(tmp_path: Path) -> None:
    create, _, _, location, _ = _features(tmp_path)
    _run(create.create(CreateCharacterRequest("qq-1", "event-1", "林远", "男")))

    with pytest.raises(LocationConflictError):
        _run(location.move(LocationMoveCommand("qq-1", "travel-1", (14, 17), (16, 17))))
