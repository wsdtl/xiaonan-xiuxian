from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

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
from game.core.world import WorldService
from game.features.chuangjian_renwu import (
    CreateCharacterFeature,
    CreateCharacterRequest,
)
from game.features.zongmen import SectFeature, SectFeatureError
from tests.support import innate_treasure_service


def _run(awaitable):
    return asyncio.run(awaitable)


def _services(tmp_path: Path):
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
    forging = ForgingService(data, database, asset, world, location, innate_treasure_service(data, database))
    forging.initialize()
    character = CharacterService(data, database, player_state, location, asset, growth, forging)
    character.initialize()
    create = CreateCharacterFeature(data, world, character)
    create.initialize()
    sect = SectService(data, database, player_state)
    sect.initialize()
    feature = SectFeature(data, sect, character, location, world, player_state)
    feature.initialize()
    return database, create, sect, feature


def _create(create, user_id: str, name: str) -> None:
    _run(create.create(CreateCharacterRequest(user_id, f"create-{user_id}", name, "男")))


def test_create_invite_accept_transfer_leave_and_disband(tmp_path: Path) -> None:
    database, create, sect, feature = _services(tmp_path)
    _create(create, "qq-1", "林远")
    _create(create, "qq-2", "白川")
    _create(create, "qq-3", "顾山")

    created = _run(feature.create("qq-1", "sect-create", "青云宗"))
    assert created.page.name == "青云宗"
    assert created.page.page == "宗主"
    assert created.page.members[0].name == "林远"
    entrance = created.page.entrance
    cave_id = created.page.cave_id
    assert cave_id.startswith("cave-")

    _run(feature.invite("qq-1", "白川", "sect-invite-2"))
    pending = _run(feature.page("qq-2"))
    assert pending.page == "待处理邀请"
    assert pending.invitation_name == "青云宗"
    joined = _run(feature.accept("qq-2", "sect-accept-2"))
    assert joined.target_name == "青云宗"
    assert [value.name for value in joined.page.members] == ["林远", "白川"]

    _run(feature.invite("qq-1", "顾山", "sect-invite-3"))
    _run(feature.reject("qq-3", "sect-reject-3"))
    assert _run(sect.membership("qq-3")) is None

    transferred = _run(feature.transfer("qq-1", "白川", "sect-transfer"))
    assert transferred.page.page == "长老"
    assert _run(sect.membership("qq-2")).role == "宗主"
    _run(feature.leave("qq-1", "sect-leave"))
    assert _run(sect.membership("qq-1")) is None

    _run(feature.disband("qq-2", "sect-disband"))
    assert _run(sect.membership("qq-2")) is None
    assert database.status().shared_entity_count == 0
    assert database.status().shared_member_count == 0
    assert database.status().shared_location_count == 0

    recreated = _run(feature.create("qq-3", "sect-recreate", "赤霄宗"))
    assert recreated.page.entrance == entrance


def test_name_and_entrance_are_unique_and_failure_is_atomic(tmp_path: Path) -> None:
    database, create, _, feature = _services(tmp_path)
    _create(create, "qq-1", "林远")
    _create(create, "qq-2", "白川")
    _run(feature.create("qq-1", "sect-create", "青云宗"))

    with pytest.raises(SectFeatureError, match="entrance_occupied"):
        _run(feature.create("qq-2", "sect-create-2", "赤霄宗"))

    assert database.status().shared_entity_count == 1
    assert database.status().shared_member_count == 1
    assert database.status().shared_location_count == 1
