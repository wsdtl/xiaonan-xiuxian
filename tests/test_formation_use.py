from __future__ import annotations

import asyncio

from game.core.asset.contracts import InventoryAdjustment
from game.core.character.contracts import CharacterCreateCommand
from game.core.database.contracts import TransactionCommand
from game.features.shiyong import UsePlan, UseRequest


def _seed(services, user_id: str) -> None:
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(
                user_id, "create-formation-use", "阵法使用", "男", (15, 17), ""
            )
        )
    )
    plan = asyncio.run(
        services.core.asset.plan_inventory_changes(
            user_id,
            (
                InventoryAdjustment("220032", "01", 1),
                InventoryAdjustment("220086", "01", 1),
                InventoryAdjustment("210001", "01", 100),
                InventoryAdjustment("220001", "01", 200),
                InventoryAdjustment("200001", "01", 100),
                InventoryAdjustment("220005", "01", 100),
                InventoryAdjustment("220059", "01", 100),
                InventoryAdjustment("230001", "01", 10000),
            ),
        )
    )
    asyncio.run(
        services.core.database.commit(
            TransactionCommand(user_id, "seed-formation-use", "测试", plan.operations, {})
        )
    )


def test_use_arms_and_replaces_formation(services) -> None:
    user_id = "formation-use-e2e"
    _seed(services, user_id)
    formation = services.core.formation
    first = asyncio.run(formation.form(user_id, "form-use-1", "530001", "黄品"))
    gateway = services.features.shiyong

    plan = asyncio.run(
        gateway.plan(UseRequest(user_id, "use-formation-1", "530001", grade="黄品"))
    )
    assert isinstance(plan, UsePlan)
    outcome = asyncio.run(gateway.execute(plan))
    assert outcome.render_key == "formation"
    assert outcome.result.prepared.formation_id == "530001"

    second = asyncio.run(formation.form(user_id, "form-use-2", "530002", "黄品"))
    plan = asyncio.run(
        gateway.plan(UseRequest(user_id, "use-formation-2", "530002", grade="黄品"))
    )
    assert isinstance(plan, UsePlan)
    asyncio.run(gateway.execute(plan))

    # 换下来的旧阵必须回阵藏，而不是凭空消失。
    old = asyncio.run(
        services.core.asset.formation_reserve_stack(user_id, first.reserve_key)
    )
    assert old.quantity == 1
    assert second.reserve_key != first.reserve_key
