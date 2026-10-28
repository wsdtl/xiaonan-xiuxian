"""四个行动根命令的分支合规由玩法判定，不由命令层。"""
from __future__ import annotations

import asyncio
from dataclasses import fields

import pytest

from game.core.character.contracts import CharacterCreateCommand
from game.features.biguan import RetreatEntry, RetreatFeatureError
from game.features.caikuang import OreGatheringFeatureError
from game.features.caiyao import HerbGatheringFeatureError
from game.features.tanxian import ExplorationEntry, ExplorationFeatureError


def _create(services, user_id: str, name: str) -> None:
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(user_id, f"create-{user_id}", name, "男", (0, 0), "")
        )
    )


def test_retreat_entry_has_no_page_fields() -> None:
    names = {field.name for field in fields(RetreatEntry)}
    assert "page" not in names
    assert "total_pages" not in names


def test_exploration_entry_has_no_page_fields() -> None:
    names = {field.name for field in fields(ExplorationEntry)}
    assert "page" not in names
    assert "total_pages" not in names


def test_exploration_exit_without_session_is_rejected(services) -> None:
    user_id = "entry-tanxian"
    _create(services, user_id, "分支探险")
    with pytest.raises(ExplorationFeatureError):
        asyncio.run(services.features.tanxian.exit(user_id, "req-tanxian"))


def test_retreat_exit_without_session_is_rejected(services) -> None:
    user_id = "entry-biguan"
    _create(services, user_id, "分支闭关")
    with pytest.raises(RetreatFeatureError):
        asyncio.run(services.features.biguan.exit(user_id, "req-biguan"))


@pytest.mark.parametrize(
    "feature_name, error_type, command",
    [
        ("caiyao", HerbGatheringFeatureError, "采药 胡说"),
        ("caikuang", OreGatheringFeatureError, "采矿 胡说"),
    ],
)
def test_invalid_action_is_rejected_by_feature(
    services, feature_name: str, error_type, command: str
) -> None:
    user_id = f"entry-{feature_name}"
    _create(services, user_id, f"分支{feature_name}")
    feature = getattr(services.features, feature_name)
    with pytest.raises(error_type):
        asyncio.run(feature.enter(user_id, f"req-{feature_name}", command))
