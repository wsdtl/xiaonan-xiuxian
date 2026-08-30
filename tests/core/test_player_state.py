from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from game.core.data import JsonDataService
from game.core.database import (
    DatabaseService,
    StateAddress,
    StateMutation,
    TransactionCommand,
)
from game.core.player_state import (
    PlayerStateConflictError,
    PlayerStateRuleError,
    PlayerStateService,
    StateTransitionCommand,
)


def _run(awaitable):
    return asyncio.run(awaitable)


def _service(tmp_path: Path) -> tuple[PlayerStateService, DatabaseService]:
    root = Path(__file__).resolve().parents[2]
    data = JsonDataService(root / "data")
    data.initialize()
    database = DatabaseService(tmp_path / "game.db")
    database.initialize()
    player_state = PlayerStateService(data, database)
    player_state.initialize()
    _run(
        database.commit(
            TransactionCommand(
                user_id="qq-1",
                request_id="create-1",
                business_type="创建人物",
                operations=(
                    StateMutation(
                        "qq-1",
                        "character",
                        "main",
                        {"姓名": "林远", "资源": {"血气": 100, "精神": 100}},
                        0,
                    ),
                    player_state.initial_mutation("qq-1"),
                ),
                payload={},
            )
        )
    )
    return player_state, database


def test_initial_snapshot_contains_three_independent_slots(tmp_path: Path) -> None:
    player_state, database = _service(tmp_path)

    current = _run(player_state.current("qq-1"))

    assert player_state.status().state_count == 13
    assert player_state.status().guard_rule_count == 15
    assert current is not None
    assert {key: value.state_id for key, value in current.states.items()} == {
        "行为": "520001",
        "队伍": "520007",
        "控制": "520009",
    }
    snapshot = _run(database.get(StateAddress("qq-1", "player_state", "main")))
    assert snapshot is not None
    assert set(snapshot.value) == {"行为", "队伍", "控制"}


def test_guard_requires_all_declared_types_but_ors_within_type(tmp_path: Path) -> None:
    player_state, _ = _service(tmp_path)

    allowed = _run(player_state.authorize("qq-1", "自主空闲或休息"))
    assert allowed.allowed is True
    assert _run(player_state.authorize("qq-1", "仅未创建")).allowed is False
    with pytest.raises(PlayerStateRuleError):
        _run(player_state.authorize("qq-1", "不存在"))
    with pytest.raises(PlayerStateRuleError):
        player_state.validate_guard_rule("不存在")

    _run(
        player_state.transition(
            StateTransitionCommand("qq-1", "rest-1", "行为", "520002")
        )
    )
    assert _run(player_state.authorize("qq-1", "自主空闲或休息")).allowed is True
    _run(
        player_state.transition(
            StateTransitionCommand("qq-1", "close-1", "行为", "520004")
        )
    )
    blocked = _run(player_state.authorize("qq-1", "自主空闲或休息"))
    assert blocked.allowed is False
    assert blocked.reason == "正在闭关。当前不能执行该行动，可使用“闭关进度”查看进度"


def test_action_guard_blocks_zero_health_but_keeps_retreat_entry_open(
    tmp_path: Path,
) -> None:
    player_state, database = _service(tmp_path)
    character = _run(database.get(StateAddress("qq-1", "character", "main")))
    assert character is not None
    _run(
        database.commit(
            TransactionCommand(
                user_id="qq-1",
                request_id="defeated-1",
                business_type="测试战败",
                operations=(
                    StateMutation(
                        "qq-1",
                        "character",
                        "main",
                        {"姓名": "林远", "资源": {"血气": 0, "精神": 0}},
                        character.version,
                    ),
                ),
                payload={},
            )
        )
    )

    blocked = _run(player_state.authorize("qq-1", "自主空闲且可行动"))
    assert blocked.allowed is False
    assert blocked.reason == "血气已经耗尽，请先闭关恢复后再行动"
    assert _run(player_state.authorize("qq-1", "自主空闲")).allowed is True


def test_state_transition_uses_json_edges_and_versions(tmp_path: Path) -> None:
    player_state, _ = _service(tmp_path)

    entered = _run(
        player_state.transition(
            StateTransitionCommand("qq-1", "team-1", "队伍", "520008")
        )
    )
    assert (entered.previous_state_id, entered.current_state_id, entered.version) == (
        "520007",
        "520008",
        2,
    )
    with pytest.raises(PlayerStateConflictError):
        _run(
            player_state.transition(
                StateTransitionCommand("qq-1", "team-2", "队伍", "520008")
            )
        )
