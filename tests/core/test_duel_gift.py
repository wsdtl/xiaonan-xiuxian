from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import game.app as game_app
from game.config import GameConfig, GameDatabaseConfig
from game.core.duel import DuelStartCommand
from game.core.gift import GiftSendCommand
from game.features.chuangjian_renwu import CreateCharacterRequest


def _run(awaitable):
    return asyncio.run(awaitable)


@pytest.fixture
def services(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        game_app,
        "game_config",
        GameConfig(
            GameDatabaseConfig(tmp_path / "game.db", tmp_path / "runtime.db", 5000)
        ),
    )
    value = game_app.build_game_services()
    yield value
    value.core.database.close()


def _create(services, count: int) -> None:
    names = ("林远", "苏青", "顾宁", "沈川")
    for index in range(count):
        _run(
            services.features.chuangjian_renwu.create(
                CreateCharacterRequest(
                    f"user-{index + 1}",
                    f"create-{index + 1}",
                    names[index],
                    "男" if index % 2 == 0 else "女",
                )
            )
        )


def test_duel_uses_leader_action_group_snapshot(services) -> None:
    _create(services, 3)
    _run(services.core.team.invite("user-1", "user-3", "team-invite"))
    _run(services.core.team.accept("user-3", "team-accept"))

    challenge = _run(
        services.core.duel.start(DuelStartCommand("user-1", "user-2", "duel-start"))
    )

    assert challenge.user_participants == ("user-1", "user-3")
    assert challenge.target_participants == ("user-2",)
    result = _run(services.core.duel.accept("user-2", "duel-accept"))
    assert result.user_participants == challenge.user_participants
    assert result.target_participants == challenge.target_participants
    assert result.actions > 0
    assert _run(services.features.qiecuo.target_name("user-2")) == "苏青"
    assert services.features.qiecuo.winner_label("left", "林远", "苏青") == "林远一方"
    assert services.features.qiecuo.winner_label("right", "林远", "苏青") == "苏青一方"
    assert (
        services.features.qiecuo.winner_label("平局", "林远", "苏青") == "双方未分胜负"
    )


def test_gift_spirit_stones_is_transactional_and_idempotent(services) -> None:
    _create(services, 2)
    before_sender = _run(services.core.character.profile("user-1")).spirit_stones
    before_target = _run(services.core.character.profile("user-2")).spirit_stones

    command = GiftSendCommand("user-1", "user-2", "gift-1", spirit_stones=3)
    result = _run(services.core.gift.send(command))
    replay = _run(services.core.gift.send(command))

    assert result.quantity == 3
    assert replay.replayed is True
    assert (
        _run(services.core.character.profile("user-1")).spirit_stones
        == before_sender - 3
    )
    assert (
        _run(services.core.character.profile("user-2")).spirit_stones
        == before_target + 3
    )
    assert _run(services.features.zengsong.target_name("user-2")) == "苏青"


def test_player_facing_short_grade_names_and_raid_results(services) -> None:
    assert services.core.asset.grade("圣").grade_id == "05"
    assert services.core.asset.grade("圣品").grade_id == "05"
    assert services.features.taofa.result_label("left") == "首领已伏诛"
    assert services.features.taofa.result_label("right") == "我方败退"
    assert services.features.taofa.result_label("平局") == "战局未分胜负"
    assert services.features.taofa.reward_note("left") == "战利已按存活修士结算。"
