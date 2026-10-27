"""无功能地点发探险/闭关时自动寻路到最近可用地点。"""
from __future__ import annotations

import asyncio

from game.core.character.contracts import CharacterCreateCommand
from game.core.world import LocationQuery


def test_wild_exploration_moves_to_function_and_starts(services) -> None:
    user_id = "auto-travel-explore"
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(
                user_id, "create-auto-explore", "自动寻路探险", "男", (0, 0), ""
            )
        )
    )
    result = asyncio.run(services.features.tanxian.start(user_id, "start-auto-explore"))
    current = asyncio.run(services.core.location.current(user_id))
    location = services.core.world.locate(LocationQuery(xy=current.xy))
    assert "探险" in location.available_functions
    assert result is not None


def test_park_retreat_moves_to_function_and_starts(services) -> None:
    user_id = "auto-travel-retreat"
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(
                user_id, "create-auto-retreat", "自动寻路闭关", "女", (15, 16), ""
            )
        )
    )
    result = asyncio.run(services.features.biguan.start(user_id, "start-auto-retreat"))
    current = asyncio.run(services.core.location.current(user_id))
    location = services.core.world.locate(LocationQuery(xy=current.xy))
    assert "闭关" in location.available_functions
    assert result is not None
