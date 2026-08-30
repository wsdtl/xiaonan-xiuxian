from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from game.core.action_group import ActionGroupService
from game.core.asset import AssetService
from game.core.character import CharacterService
from game.core.data import JsonDataService
from game.core.database import DatabaseService
from game.core.forging import ForgingService
from game.core.growth import GrowthService
from game.core.location import LocationMoveCommand, LocationService
from game.core.player_state import PlayerStateService
from game.core.pool import PoolService
from game.core.sect import SectService
from game.core.team import TeamService
from game.core.world import WorldService
from game.features.chuangjian_renwu import (
    CreateCharacterFeature,
    CreateCharacterRequest,
)
from game.features.xinglu import TravelFeature, TravelQueryError, TravelRequest
from game.features.zongmen import SectFeature
from game.features.zongmen_shanmen import GateFeature, GateFeatureError
from game.features.zongmen_tongxing import SectFollowFeature
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
    follow = SectFollowFeature(data, sect, character, location, state, team)
    follow.initialize()
    gate = GateFeature(data, sect, location, state, action_group)
    gate.initialize()
    travel = TravelFeature(world, character, location, action_group, state)
    travel.initialize()
    return create, team, sect, sect_feature, follow, gate, location, travel


def _create(create: CreateCharacterFeature, user_id: str, name: str) -> None:
    _run(
        create.create(CreateCharacterRequest(user_id, f"create-{user_id}", name, "男"))
    )


def _join(sect_feature: SectFeature, user_id: str, name: str) -> None:
    _run(sect_feature.invite("qq-1", name, f"invite-{user_id}"))
    _run(sect_feature.accept(user_id, f"accept-{user_id}"))


def test_gate_enters_and_leaves_the_same_cave_atomically(tmp_path: Path) -> None:
    create, _, sect, sect_feature, _, gate, location, travel = _services(tmp_path)
    _create(create, "qq-1", "林远")
    _create(create, "qq-2", "白川")
    _run(sect_feature.create("qq-1", "sect-create", "青云宗"))
    _join(sect_feature, "qq-2", "白川")

    cave = _run(gate.enter("qq-1", "gate-enter"))
    assert cave.action == "进入"
    assert cave.participant_count == 1
    assert _run(location.current("qq-1")).space_type == "宗门洞天"
    member = _run(sect.membership("qq-1"))
    assert member is not None
    sect_snapshot = _run(sect.sect(member.sect_id))
    assert sect_snapshot is not None
    assert _run(location.current("qq-1")).space_id == sect_snapshot.cave_id
    assert _run(location.nearby_players("qq-1")).values == ()
    assert _run(location.nearby_players("qq-2")).values == ()

    with pytest.raises(TravelQueryError, match="宗门洞天"):
        _run(travel.travel(TravelRequest("qq-1", "cave-travel", "天衡城")))

    left = _run(gate.leave("qq-1", "gate-leave"))
    assert left.action == "离开"
    current = _run(location.current("qq-1"))
    assert (current.space_type, current.space_id, current.xy) == (
        "地表",
        "",
        (15, 17),
    )


def test_gate_follows_sect_leader_and_rejects_external_member(tmp_path: Path) -> None:
    create, team, _, sect_feature, follow, gate, location, _ = _services(tmp_path)
    _create(create, "qq-1", "林远")
    _create(create, "qq-2", "白川")
    _create(create, "qq-3", "顾山")
    _run(sect_feature.create("qq-1", "sect-create", "青云宗"))
    _join(sect_feature, "qq-2", "白川")
    _run(follow.assemble("qq-1", "follow-assemble"))
    _run(follow.join("qq-2", "follow-join"))
    _run(gate.enter("qq-1", "gate-enter"))
    assert _run(location.current("qq-2")).space_type == "宗门洞天"

    _run(gate.leave("qq-1", "gate-leave"))
    _run(follow.disband("qq-1", "follow-disband"))
    _run(location.move(LocationMoveCommand("qq-1", "move-1", (15, 17), (25, 33))))
    _run(location.move(LocationMoveCommand("qq-3", "move-3", (15, 17), (25, 33))))
    _run(sect_feature.create("qq-3", "sect-create-3", "赤霄宗"))
    _run(location.move(LocationMoveCommand("qq-1", "move-back", (25, 33), (15, 17))))
    _run(location.move(LocationMoveCommand("qq-3", "move-back-3", (25, 33), (15, 17))))
    _run(team.invite("qq-1", "qq-3", "team-invite"))
    _run(team.accept("qq-3", "team-accept"))
    with pytest.raises(GateFeatureError, match="external_member"):
        _run(gate.enter("qq-1", "gate-external"))


def test_gate_buttons_follow_current_space(tmp_path: Path) -> None:
    create, _, _, sect_feature, _, gate, _, _ = _services(tmp_path)
    _create(create, "qq-1", "林远")
    _run(sect_feature.create("qq-1", "sect-create", "青云宗"))

    assert tuple(value.command for value in _run(gate.gate_actions("qq-1"))) == (
        "入山门",
    )
    _run(gate.enter("qq-1", "gate-enter"))
    assert tuple(value.command for value in _run(gate.gate_actions("qq-1"))) == (
        "出山门",
        "灵藏",
        "万珍殿",
        "藏经阁",
        "百炼堂",
        "丹鼎阁",
        "演阵台",
        "灵脉",
        "灵田",
    )
