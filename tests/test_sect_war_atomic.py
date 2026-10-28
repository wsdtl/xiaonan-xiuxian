"""宗门战接受失败不能留下半状态。"""

from __future__ import annotations

import asyncio

import pytest

from game.core.character.contracts import CharacterCreateCommand
from game.core.database.contracts import TransactionCommand
from game.core.sect_war import SectWarError


def _create(services, uid: str, name: str) -> None:
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(uid, f"创建:{uid}", name, "男", (15, 17), "")
        )
    )


def _seed(services, sect_id: str, leader: str) -> None:
    mutation = asyncio.run(
        services.core.sect_assets.plan_spirit_stone_change(sect_id, 1000)
    )
    asyncio.run(
        services.core.database.commit(
            TransactionCommand(leader, f"种子:{sect_id}", "测试种子", (mutation,), {})
        )
    )


def test_target_wager_failure_keeps_war_pending(services) -> None:
    a, b = "P:原子甲", "P:原子乙"
    _create(services, a, "原子甲宗")
    _create(services, b, "原子乙宗")
    sect_a = asyncio.run(services.core.sect.create(a, "建甲", "原子甲宗", (15, 17)))
    sect_b = asyncio.run(services.core.sect.create(b, "建乙", "原子乙宗", (15, 17)))
    _seed(services, sect_a.sect_id, a)
    asyncio.run(services.core.sect.assemble(a, "同行甲"))
    asyncio.run(services.core.sect.assemble(b, "同行乙"))
    asyncio.run(
        services.core.sect_war.challenge(a, "原子乙宗", 100, "约战")
    )
    with pytest.raises(SectWarError, match="wager_insufficient"):
        asyncio.run(services.core.sect_war.accept_and_start(b, "接受"))
    current = asyncio.run(services.core.sect_war.current(a, "查看"))
    assert current.status == "待应战"
    assert current.defender_count == 0
