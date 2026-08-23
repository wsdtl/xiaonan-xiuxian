from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from game.cmd.通用.托管 import runtime as hosting_runtime
from game.core.action_group import ActionGroupService
from game.core.asset import AssetService
from game.core.character import CharacterService
from game.core.data import JsonDataService
from game.core.database import DatabaseService
from game.core.forging import ForgingService
from game.core.growth import GrowthService
from game.core.hosting import HostingError, HostingService
from game.core.location import LocationService
from game.core.player_state import PlayerStateService, StateTransitionCommand
from game.core.pool import PoolService
from game.core.sect import SectService
from game.core.team import TeamService
from game.core.world import WorldService
from game.features.chuangjian_renwu import (
    CreateCharacterFeature,
    CreateCharacterRequest,
)
from game.features.duiwu import TeamFeature, TeamFeatureError
from game.features.tuoguan import HostingFeature
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
    hosting = HostingService(data, database, state, action_group)
    hosting.initialize()
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
    team_feature = TeamFeature(data, team, character, location, state)
    team_feature.initialize()
    hosting_feature = HostingFeature(data, hosting)
    hosting_feature.initialize()
    return state, create, team_feature, hosting, hosting_feature


def _create(create: CreateCharacterFeature, user_id: str, name: str) -> None:
    _run(
        create.create(CreateCharacterRequest(user_id, f"create-{user_id}", name, "男"))
    )


def _join(team: TeamFeature) -> None:
    _run(team.invite("qq-1", "白川", "invite-qq-2"))
    _run(team.accept("qq-2", "accept-qq-2"))


def test_personal_hosting_is_persisted_replayed_and_cancelled(tmp_path: Path) -> None:
    state, create, _, hosting, feature = _services(tmp_path)
    _create(create, "qq-1", "林远")

    started = _run(feature.start("qq-1", "host-start", ("探险", "闭关")))
    assert started.session is not None
    assert started.session.mode == "personal"
    assert started.session.participant_user_ids == ("qq-1",)
    assert started.session.activities == ("探险", "闭关")
    snapshot = _run(state.current("qq-1"))
    assert snapshot is not None
    assert snapshot.states["控制"].state_id == "520010"
    assert dict(snapshot.states["控制"].context) == {
        "托管编号": started.session.session_id,
        "托管身份": "单人",
        "托管领队": None,
        "同行类型": "独行",
        "同行编号": None,
    }
    replayed = _run(hosting.start("qq-1", "host-start", ("探险", "闭关")))
    assert replayed.session_id == started.session.session_id

    cancelled = _run(feature.cancel("qq-1", "host-cancel"))
    assert cancelled.session is not None
    assert cancelled.session.participant_user_ids == ("qq-1",)
    snapshot = _run(state.current("qq-1"))
    assert snapshot is not None
    assert snapshot.states["控制"].state_id == "520009"
    assert dict(snapshot.states["控制"].context) == {}
    latest = _run(feature.current("qq-1"))
    assert latest.active is False
    assert latest.session is not None
    assert latest.session.status == "已取消"
    assert "当前活动保留" in latest.session.last_message


def test_team_leader_hosts_and_cancels_every_member_atomically(tmp_path: Path) -> None:
    state, create, team, hosting, _ = _services(tmp_path)
    _create(create, "qq-1", "林远")
    _create(create, "qq-2", "白川")
    _join(team)

    session = _run(hosting.start("qq-1", "team-host", ("采药", "采矿")))
    assert session.mode == "team"
    snapshots = _run(state.current_many(("qq-1", "qq-2")))
    assert [snapshot.states["控制"].context["托管身份"] for snapshot in snapshots] == [
        "领队",
        "跟随",
    ]
    assert {snapshot.states["控制"].context["托管编号"] for snapshot in snapshots} == {
        session.session_id
    }
    with pytest.raises(HostingError, match="member_cannot_cancel"):
        _run(hosting.cancel("qq-2", "member-cancel"))
    with pytest.raises(TeamFeatureError, match="actor_busy"):
        _run(team.leave("qq-2", "leave-hosting"))

    _run(hosting.cancel("qq-1", "team-cancel"))
    snapshots = _run(state.current_many(("qq-1", "qq-2")))
    assert {snapshot.states["控制"].state_id for snapshot in snapshots} == {"520009"}


def test_leader_cannot_host_when_a_participant_is_busy(tmp_path: Path) -> None:
    state, create, team, hosting, _ = _services(tmp_path)
    _create(create, "qq-1", "林远")
    _create(create, "qq-2", "白川")
    _join(team)
    _run(state.transition(StateTransitionCommand("qq-2", "busy", "行为", "520005")))

    with pytest.raises(HostingError, match="participant_busy"):
        _run(hosting.start("qq-1", "busy-host", ("探险",)))
    snapshots = _run(state.current_many(("qq-1", "qq-2")))
    assert {snapshot.states["控制"].state_id for snapshot in snapshots} == {"520009"}


def test_custom_plan_advances_in_fixed_thirty_minute_slots(tmp_path: Path) -> None:
    state, create, _, hosting, _ = _services(tmp_path)
    _create(create, "qq-1", "林远")
    started_at = datetime(2026, 8, 21, 4, 0, tzinfo=timezone.utc)
    session = _run(
        hosting.start(
            "qq-1",
            "custom-plan",
            ("探险", "探险", "闭关"),
            now=started_at,
        )
    )

    execution = _run(hosting.claim_execution(session.session_id, now=started_at))
    assert execution is not None
    assert (execution.activity, execution.phase, execution.command) == (
        "探险",
        "执行开始",
        "开始探险",
    )
    assert _run(
        hosting.authorize_execution(
            user_id="qq-1",
            request_id=execution.request_id,
            activity="探险",
            phase="start",
        )
    )
    assert not _run(
        hosting.authorize_execution(
            user_id="qq-1",
            request_id="伪造请求",
            activity="探险",
            phase="start",
        )
    )

    _run(state.transition(StateTransitionCommand("qq-1", "explore", "行为", "520005")))
    assert _run(hosting.verify_execution(execution))
    waiting = _run(
        hosting.complete_execution(execution, success=True, now=started_at)
    )
    assert waiting is not None
    assert waiting.phase == "待结束"
    assert waiting.next_trigger_at == started_at + timedelta(minutes=30)
    assert (
        _run(
            hosting.claim_execution(
                session.session_id, now=started_at + timedelta(minutes=29, seconds=59)
            )
        )
        is None
    )

    ending = _run(
        hosting.claim_execution(
            session.session_id, now=started_at + timedelta(minutes=30)
        )
    )
    assert ending is not None
    assert (ending.phase, ending.command) == ("执行结束", "探险结束")
    _run(state.finish_behavior("qq-1", "finish-explore"))
    advanced = _run(
        hosting.complete_execution(
            ending, success=True, now=started_at + timedelta(minutes=30)
        )
    )
    assert advanced is not None
    assert advanced.current_index == 1
    assert advanced.current_activity == "探险"
    assert advanced.phase == "待开始"


def test_failed_step_pauses_until_the_leader_resumes(tmp_path: Path) -> None:
    _, create, team, hosting, _ = _services(tmp_path)
    _create(create, "qq-1", "林远")
    _create(create, "qq-2", "白川")
    _join(team)
    started_at = datetime(2026, 8, 21, 4, 0, tzinfo=timezone.utc)
    session = _run(
        hosting.start("qq-1", "pause-plan", ("采药", "采矿"), now=started_at)
    )
    execution = _run(hosting.claim_execution(session.session_id, now=started_at))
    assert execution is not None
    paused = _run(
        hosting.complete_execution(
            execution,
            success=False,
            error="当前地形没有灵植资源池",
            now=started_at,
        )
    )
    assert paused is not None
    assert paused.status == "已暂停"
    assert paused.phase == "待开始"
    assert paused.next_trigger_at is None
    assert "灵植资源池" in paused.last_error
    with pytest.raises(HostingError, match="member_cannot_resume"):
        _run(hosting.resume("qq-2", "member-resume", now=started_at))

    resumed = _run(hosting.resume("qq-1", "leader-resume", now=started_at))
    assert resumed.status == "运行中"
    assert resumed.next_trigger_at == started_at


def test_twenty_four_hour_limit_releases_every_participant(tmp_path: Path) -> None:
    state, create, team, hosting, _ = _services(tmp_path)
    _create(create, "qq-1", "林远")
    _create(create, "qq-2", "白川")
    _join(team)
    started_at = datetime(2026, 8, 21, 4, 0, tzinfo=timezone.utc)
    session = _run(
        hosting.start("qq-1", "expiry-plan", ("闭关",), now=started_at)
    )

    assert (
        _run(
            hosting.claim_execution(
                session.session_id, now=started_at + timedelta(hours=24)
            )
        )
        is None
    )
    assert _run(hosting.current("qq-1")) is None
    latest = _run(hosting.latest("qq-2"))
    assert latest is not None
    assert latest.status == "已到期"
    assert "24小时" in latest.last_message
    snapshots = _run(state.current_many(("qq-1", "qq-2")))
    assert {snapshot.states["控制"].state_id for snapshot in snapshots} == {"520009"}


def test_local_runtime_dispatches_one_claimed_command_and_schedules_only_the_end(
    tmp_path: Path, monkeypatch
) -> None:
    state, create, _, hosting, feature = _services(tmp_path)
    _create(create, "qq-1", "林远")
    session = _run(hosting.start("qq-1", "runtime-plan", ("闭关",)))
    dispatched = []
    scheduled = []

    async def fake_dispatch(*, user_id: str, raw_message: str, event_id: str):
        dispatched.append((user_id, raw_message, event_id))
        await state.transition(
            StateTransitionCommand(user_id, event_id, "行为", "520004")
        )
        return SimpleNamespace(matched=True, replies=[])

    monkeypatch.setattr(
        hosting_runtime,
        "current_game_services",
        lambda: SimpleNamespace(features=SimpleNamespace(tuoguan=feature)),
    )
    monkeypatch.setattr(hosting_runtime, "dispatch_local_message", fake_dispatch)
    monkeypatch.setattr(hosting_runtime, "schedule_plan", scheduled.append)

    _run(hosting_runtime.run_hosting_plan(session.session_id))

    assert len(dispatched) == 1
    assert dispatched[0][:2] == ("qq-1", "开始闭关")
    assert len(scheduled) == 1
    current = _run(hosting.current("qq-1"))
    assert current is not None
    assert current.phase == "待结束"
    assert current.next_trigger_at is not None
    remaining = (current.next_trigger_at - datetime.now(timezone.utc)).total_seconds()
    assert 1795 <= remaining <= 1800
