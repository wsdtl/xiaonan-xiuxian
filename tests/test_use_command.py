from __future__ import annotations

import asyncio

from game.core.asset.contracts import CultivationAcquisition
from game.core.character.contracts import CharacterCreateCommand
from game.core.database.contracts import TransactionCommand


def test_use_target_and_equip_card(services) -> None:
    """真实人物 + 真实道藏：使用功法能解析位置并走装配事务。"""

    user_id = "use-e2e"
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(
                user_id, "create-use", "使用测试", "男", (15, 17), ""
            )
        )
    )
    plan = asyncio.run(
        services.core.asset.plan_cultivation_acquisitions(
            user_id, (CultivationAcquisition("功法", "400001", "01"),)
        )
    )
    asyncio.run(
        services.core.database.commit(
            TransactionCommand(user_id, "seed-use-card", "测试置备", plan.operations, {})
        )
    )

    feature = services.features.renwu_peiyang
    target = asyncio.run(feature.resolve_use_target(user_id, "400001"))
    assert target.category == "功法"
    assert target.slots == (1, 2, 3, 4, 5, 6)

    result = asyncio.run(feature.use(user_id, "use-card-1", target, "01", 1))
    assert result.category == "功法"
    assert result.slot == 1
    assert result.content_name
