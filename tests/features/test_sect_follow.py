from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from game.core.action_group import ActionGroupError, ActionGroupService
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
from game.features.xinglu import TravelFeature, TravelRequest
from game.features.zongmen import SectFeature
from game.features.zongmen_tongxing import SectFollowFeature, SectFollowFeatureError
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
    state = PlayerStateService(data, database)
    state.initialize()
    team = TeamService(data, database, state)
    team.initialize()
    sect = SectService(data, database, state)
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
        data, database, state, location, asset, growth, forging
    )
    character.initialize()
    create = CreateCharacterFeature(data, world, character)
    create.initialize()
    sect_feature = SectFeature(data, sect, character, location, world, state)
    sect_feature.initialize()
    follow_feature = SectFollowFeature(data, sect, character, location, state, team)
    follow_feature.initialize()
    travel = TravelFeature(world, character, location, action_group, state)
    travel.initialize()
    return (
        create,
        team,
        sect,
        action_group,
        location,
        sect_feature,
        follow_feature,
        travel,
    )


def _create(create: CreateCharacterFeature, user_id: str, name: str) -> None:
    _run(
        create.create(CreateCharacterRequest(user_id, f"create-{user_id}", name, "男"))
    )


def test_assemble_join_travel_and_end_follow(tmp_path: Path) -> None:
    create, _, sect, action_group, location, sect_feature, follow, travel = _services(
        tmp_path
    )
    _create(create, "qq-1", "林远")
    _create(create, "qq-2", "白川")

    _run(sect_feature.create("qq-1", "sect-create", "青云宗"))
    _run(sect_feature.invite("qq-1", "白川", "sect-invite"))
    _run(sect_feature.accept("qq-2", "sect-accept"))
    assembled = _run(follow.assemble("qq-1", "follow-assemble"))
    assert assembled.page.page == "宗主"
    assert assembled.page.members[0].name == "林远"
    joined = _run(follow.join("qq-2", "follow-join"))
    assert [value.name for value in joined.page.members] == ["林远", "白川"]
    assert _run(action_group.participants("qq-1")) == ("qq-1", "qq-2")
    with pytest.raises(ActionGroupError, match="member_cannot_start"):
        _run(action_group.participants("qq-2"))

    public = _run(sect.public_follow_many(("qq-1", "qq-2")))
    assert [
        (value.following, value.leading, value.member_count) for value in public
    ] == [
        (True, True, 2),
        (True, False, 2),
    ]

    result = _run(travel.travel(TravelRequest("qq-1", "sect-travel", "天衡城")))
    assert result.participant_user_ids == ("qq-1", "qq-2")
    assert _run(location.current("qq-1")).xy == result.plan.destination.xy
    assert _run(location.current("qq-2")).xy == result.plan.destination.xy
    _run(follow.disband("qq-1", "follow-disband"))
    assert _run(action_group.participants("qq-1")) == ("qq-1",)


def test_team_and_sect_follow_are_rejected_as_conflicting_states(
    tmp_path: Path,
) -> None:
    create, team, _, _, _, sect_feature, follow, _ = _services(tmp_path)
    _create(create, "qq-1", "林远")
    _create(create, "qq-2", "白川")
    _run(sect_feature.create("qq-1", "sect-create", "青云宗"))
    _run(sect_feature.invite("qq-1", "白川", "sect-invite"))
    _run(sect_feature.accept("qq-2", "sect-accept"))
    _run(team.invite("qq-1", "qq-2", "team-invite"))
    _run(team.accept("qq-2", "team-accept"))

    with pytest.raises(SectFollowFeatureError, match="fellowship_conflict"):
        _run(follow.assemble("qq-1", "follow-assemble"))


def test_follow_join_requires_same_location(tmp_path: Path) -> None:
    create, _, _, _, _, sect_feature, follow, travel = _services(tmp_path)
    _create(create, "qq-1", "林远")
    _create(create, "qq-2", "白川")
    _run(sect_feature.create("qq-1", "sect-create", "青云宗"))
    _run(sect_feature.invite("qq-1", "白川", "sect-invite"))
    _run(sect_feature.accept("qq-2", "sect-accept"))
    _run(follow.assemble("qq-1", "follow-assemble"))
    _run(travel.travel(TravelRequest("qq-2", "solo-travel", "天衡城")))

    with pytest.raises(SectFollowFeatureError, match="not_same_location"):
        _run(follow.join("qq-2", "follow-join"))
