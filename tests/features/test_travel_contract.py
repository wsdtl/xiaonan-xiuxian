from __future__ import annotations

import asyncio
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest

from game.core.action_group import ActionGroupService
from game.core.asset import AssetService
from game.core.character import CharacterService
from game.core.data import JsonDataService
from game.core.database import DatabaseService
from game.core.forging import ForgingService
from game.core.growth import GrowthService
from game.core.location import LocationService
from game.core.player_state import PlayerStateService
from game.core.pool import PoolService
from game.core.sect import SectService
from game.core.team import TeamService
from game.core.world import WorldService
from game.features.chuangjian_renwu import (
    CreateCharacterFeature,
    CreateCharacterRequest,
)
from game.features.weizhi import PositionAction
from game.features.xinglu import TravelFeature, TravelQueryError, TravelRequest
from message import DocumentMessage
from message.renderers.plain_text import render_plain_text
from tests.support import innate_treasure_service


def _run(awaitable):
    return asyncio.run(awaitable)


def _features(
    tmp_path: Path,
) -> tuple[CreateCharacterFeature, TravelFeature, DatabaseService]:
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
    team = TeamService(data, database, player_state)
    team.initialize()
    sect = SectService(data, database, player_state)
    sect.initialize()
    action_group = ActionGroupService(team, sect)
    action_group.initialize()
    location = LocationService(data, database, world)
    location.initialize()
    asset = AssetService(data, database)
    asset.initialize()
    forging = ForgingService(data, database, asset, world, location, innate_treasure_service(data, database))
    forging.initialize()
    character = CharacterService(
        data, database, player_state, location, asset, growth, forging
    )
    character.initialize()
    create = CreateCharacterFeature(data, world, character)
    create.initialize()
    travel = TravelFeature(world, character, location, action_group, player_state)
    travel.initialize()
    return create, travel, database


def test_travel_by_location_name_immediately_moves_character(tmp_path: Path) -> None:
    create, travel, database = _features(tmp_path)
    _run(create.create(CreateCharacterRequest("qq-1", "create-1", "林远", "男")))

    result = _run(travel.travel(TravelRequest("qq-1", "travel-1", "天衡城")))
    snapshot = _run(database.get_location("qq-1"))

    assert result.plan.destination.location_name == "天衡城"
    assert result.plan.realm_name == "灵动"
    assert snapshot is not None
    assert snapshot.xy == result.plan.destination.xy
    assert database.status().transaction_count == 2


def test_travel_command_renders_journey_destination_and_available_functions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    create, travel, _ = _features(tmp_path)
    _run(create.create(CreateCharacterRequest("qq-1", "create-1", "林远", "男")))

    class RecordingManager:
        message: DocumentMessage | None = None

        async def send(self, message: DocumentMessage) -> None:
            self.message = message

    command_module = import_module("game.cmd.通用.行路")

    class PositionButtons:
        @staticmethod
        def open_location_functions(functions):
            assert "修士" in functions
            return ("修士",)

        @staticmethod
        def position_actions(functions, *, plant_pool, mineral_pool):
            assert functions == ("修士",)
            assert plant_pool == ("灵植-高地",)
            assert mineral_pool == ("灵矿-高地",)
            return (
                PositionAction(
                    "location.cultivators",
                    "附近修士",
                    "附近 修士",
                    "callback",
                    "primary",
                ),
            )

    monkeypatch.setattr(
        command_module,
        "current_game_services",
        lambda: SimpleNamespace(
            features=SimpleNamespace(xinglu=travel, weizhi=PositionButtons())
        ),
    )
    manager = RecordingManager()
    _run(
        command_module.travel(
            user_id="qq-1",
            message="天衡城",
            message_context=SimpleNamespace(request_id="travel-1"),
            manager=manager,
        )
    )

    assert manager.message is not None
    content = render_plain_text(manager.message.document)
    assert "抵达 · 天衡城" in content
    assert "行路 · 引息轻行" in content
    assert "地点: 天衡城" in content
    assert "区域: 天衡州" in content
    assert "可用功能" not in content
    assert tuple(action.data for action in manager.message.document.actions) == (
        "附近 修士",
    )


def test_travel_by_xy_returns_named_or_wilderness_location_fact(tmp_path: Path) -> None:
    create, travel, _ = _features(tmp_path)
    _run(create.create(CreateCharacterRequest("qq-1", "create-1", "林远", "男")))

    result = _run(travel.travel(TravelRequest("qq-1", "travel-1", "16 17")))

    assert result.plan.destination.xy == (16, 17)
    assert result.plan.destination.location_name == ""
    assert "（16, 17）" in result.plan.narrative[-2]


@pytest.mark.parametrize("destination", ("", "1", "一 二", "1 2 3", "100 10"))
def test_invalid_or_same_destination_has_no_position_side_effect(
    tmp_path: Path,
    destination: str,
) -> None:
    create, travel, database = _features(tmp_path)
    _run(create.create(CreateCharacterRequest("qq-1", "create-1", "林远", "男")))

    with pytest.raises(TravelQueryError):
        _run(travel.travel(TravelRequest("qq-1", "travel-1", destination)))

    snapshot = _run(database.get_location("qq-1"))
    assert snapshot is not None
    assert snapshot.xy == (15, 17)
    assert database.status().transaction_count == 1
