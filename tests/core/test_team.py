from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path

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
from game.core.team import TeamConflictError, TeamService
from game.core.world import WorldService
from game.features.chuangjian_renwu import (
    CreateCharacterFeature,
    CreateCharacterRequest,
)
from game.features.duiwu import TeamFeature, TeamFeatureError
from game.features.xinglu import TravelFeature, TravelRequest
from message import render_local_message
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
    feature = TeamFeature(data, team, character, location, player_state)
    feature.initialize()
    travel = TravelFeature(world, character, location, action_group, player_state)
    travel.initialize()
    return database, player_state, team, location, create, feature, travel


def _create(create: CreateCharacterFeature, user_id: str, name: str) -> None:
    _run(
        create.create(CreateCharacterRequest(user_id, f"create-{user_id}", name, "男"))
    )


def _join(feature: TeamFeature, leader: str, target_name: str, target: str) -> None:
    _run(feature.invite(leader, target_name, f"invite-{target}"))
    _run(feature.accept(target, f"accept-{target}"))


def test_team_invitation_order_public_count_and_group_travel(tmp_path: Path) -> None:
    _, _, team, location, create, feature, travel = _services(tmp_path)
    _create(create, "qq-1", "林远")
    _create(create, "qq-2", "白川")
    _create(create, "qq-3", "顾山")

    _join(feature, "qq-1", "白川", "qq-2")
    _join(feature, "qq-1", "顾山", "qq-3")

    membership = _run(team.membership("qq-1"))
    assert membership is not None
    assert membership.team.member_user_ids == ("qq-1", "qq-2", "qq-3")
    assert _run(team.action_participants("qq-1")) == ("qq-1", "qq-2", "qq-3")
    with pytest.raises(TeamConflictError, match="member_cannot_start"):
        _run(team.action_participants("qq-2"))
    public = _run(team.public_many(("qq-1", "qq-2", "qq-3")))
    assert [(value.grouped, value.member_count) for value in public] == [
        (True, 3),
        (True, 3),
        (True, 3),
    ]
    page = _run(feature.page("qq-1"))
    reply = import_module("game.cmd.通用.队伍.reply")
    rendered = render_local_message(
        reply.page(feature.copy(), page, feature.page_actions(page))
    )
    assert "人数" in rendered.content
    assert "3/3" in rendered.content
    assert "林远 · 队长" in rendered.content
    assert "白川 · 队员" in rendered.content
    assert all(action.data != "队伍 邀请 " for action in rendered.actions)

    result = _run(travel.travel(TravelRequest("qq-1", "travel-team", "天衡城")))
    assert result.participant_user_ids == ("qq-1", "qq-2", "qq-3")
    locations = tuple(
        _run(location.current(user_id)).xy for user_id in result.participant_user_ids
    )
    assert locations == (result.plan.destination.xy,) * 3


def test_leader_leave_transfers_then_two_person_leave_disbands(tmp_path: Path) -> None:
    _, _, team, _, create, feature, _ = _services(tmp_path)
    _create(create, "qq-1", "林远")
    _create(create, "qq-2", "白川")
    _create(create, "qq-3", "顾山")
    _join(feature, "qq-1", "白川", "qq-2")
    _join(feature, "qq-1", "顾山", "qq-3")

    _run(feature.leave("qq-1", "leave-leader"))
    successor = _run(team.membership("qq-2"))
    assert successor is not None
    assert successor.role == "队长"
    assert successor.team.member_user_ids == ("qq-2", "qq-3")
    assert _run(team.membership("qq-1")) is None

    _run(feature.leave("qq-3", "leave-member"))
    assert _run(team.membership("qq-2")) is None
    assert _run(team.membership("qq-3")) is None


def test_invitation_expires_and_full_team_rejects_more_members(tmp_path: Path) -> None:
    _, _, team, _, create, feature, _ = _services(tmp_path)
    for user_id, name in (
        ("qq-1", "林远"),
        ("qq-2", "白川"),
        ("qq-3", "顾山"),
        ("qq-4", "沈照"),
    ):
        _create(create, user_id, name)
    started = datetime(2026, 8, 17, tzinfo=timezone.utc)
    _run(team.invite("qq-1", "qq-2", "expires", now=started))
    with pytest.raises(TeamConflictError, match="invitation_expired"):
        _run(
            team.accept(
                "qq-2",
                "accept-expired",
                now=started + timedelta(minutes=11),
            )
        )

    _join(feature, "qq-1", "白川", "qq-2")
    _join(feature, "qq-1", "顾山", "qq-3")
    with pytest.raises(TeamFeatureError, match="team_full"):
        _run(feature.invite("qq-1", "沈照", "invite-fourth"))
