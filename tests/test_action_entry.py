"""四个行动根命令的分支合规由玩法判定，不由命令层。"""
from __future__ import annotations

import asyncio

import pytest

from game.core.character.contracts import CharacterCreateCommand
from game.features.biguan import RetreatFeatureError
from game.features.caikuang import OreGatheringFeatureError
from game.features.caiyao import HerbGatheringFeatureError
from game.features.tanxian import ExplorationFeatureError


def _create(services, user_id: str, name: str) -> None:
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(user_id, f"create-{user_id}", name, "男", (0, 0), "")
        )
    )


@pytest.mark.parametrize(
    "feature_name, error_type, command",
    [
        ("tanxian", ExplorationFeatureError, "探险 胡说"),
        ("biguan", RetreatFeatureError, "闭关 胡说"),
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
