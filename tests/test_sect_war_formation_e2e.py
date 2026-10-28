from __future__ import annotations

import asyncio
from pathlib import Path

from game.core.asset import ItemRef, format_item_ref
from game.core.character.contracts import CharacterCreateCommand
from game.core.database.contracts import SharedEntityMutation, TransactionCommand
from game.features.shiyong import UsePlan, UseRequest

DATA = Path(__file__).resolve().parents[1] / "data"


def _create_character(services, user_id: str, name: str, xy: tuple[int, int]) -> None:
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(user_id, f"create-{user_id}", name, "男", xy, "")
        )
    )


def _seed_sect_stones(services, sect_id: str, leader: str) -> None:
    mutation = asyncio.run(
        services.core.sect_assets.plan_spirit_stone_change(sect_id, 100_000)
    )
    asyncio.run(
        services.core.database.commit(
            TransactionCommand(
                leader, f"seed-stones-{sect_id}", "测试种子", (mutation,), {}
            )
        )
    )


def _seed_formation(services, user_id: str, formation_id: str = "530001") -> str:
    plan = asyncio.run(
        services.core.asset.plan_formation_reserve_acquisition(
            user_id, formation_id, "01"
        )
    )
    asyncio.run(
        services.core.database.commit(
            TransactionCommand(
                user_id, f"seed-formation-{user_id}", "测试种子", (plan.operation,), {}
            )
        )
    )
    return plan.stack.state_key


def _seed_wanzhen_product(services, sect_id: str, leader: str) -> str:
    entry_key = format_item_ref(ItemRef(item="100001", grade="01"))
    value = {
        "名称": f"万珍殿-{sect_id}",
        "宗门编号": sect_id,
        "条目": {
            entry_key: {
                "类别": "丹药",
                "编号": "100001",
                "名称": "清心散",
                "品级": "01",
                "数量": 1,
                "实际投入": {},
            }
        },
    }
    asyncio.run(
        services.core.database.commit(
            TransactionCommand(
                leader,
                f"seed-wanzhen-{sect_id}",
                "测试种子",
                (SharedEntityMutation("宗门万珍殿", sect_id, value, 0),),
                {},
            )
        )
    )
    return entry_key


def test_two_sects_real_war_with_personal_formations_and_wanzhen_claim(services) -> None:
    """两个真实宗门各带个人阵法开战；万珍殿成品可由宗主直接领取。"""

    a = "sect-formation-a"
    b = "sect-formation-b"
    _create_character(services, a, "甲宗宗主", (15, 17))
    _create_character(services, b, "乙宗宗主", (15, 17))

    sect_a = asyncio.run(services.core.sect.create(a, "create-sect-a", "甲阵宗", (15, 17)))
    sect_b = asyncio.run(services.core.sect.create(b, "create-sect-b", "乙阵宗", (15, 17)))
    _seed_sect_stones(services, sect_a.sect_id, a)
    _seed_sect_stones(services, sect_b.sect_id, b)

    # 每个宗主单位先有自己的待战阵法（真实阵藏 -> 使用入口入槽）。
    _seed_formation(services, a)
    _seed_formation(services, b)
    gateway = services.features.shiyong
    for user_id, formation_id, request_id in (
        (a, "530001", "use-a"),
        (b, "530001", "use-b"),
    ):
        plan = asyncio.run(
            gateway.plan(
                UseRequest(user_id, request_id, formation_id, grade="黄品")
            )
        )
        assert isinstance(plan, UsePlan)
        asyncio.run(gateway.execute(plan))
    assert asyncio.run(services.core.formation.prepared(a)) is not None
    assert asyncio.run(services.core.formation.prepared(b)) is not None

    # 双方开启同行，宗门战才能锁定成员。
    asyncio.run(services.core.sect.assemble(a, "follow-a"))
    asyncio.run(services.core.sect.assemble(b, "follow-b"))

    # 万珍殿：同一宗门、宗主直接领取一份成品（开战前，宗主不在宗门战活动中）。
    entry_key = _seed_wanzhen_product(services, sect_a.sect_id, a)
    claimed = asyncio.run(
        services.features.zongmen_wanzhen.claim(a, "claim-a", entry_key, 1)
    )
    assert claimed.action == "领取"
    snapshot = asyncio.run(services.core.asset.snapshot(a))
    assert any(
        getattr(entry, "content_id", "") == "100001"
        and int(getattr(entry, "quantity", 0) or 0) == 1
        for entry in snapshot.entries
    )

    war = asyncio.run(
        services.core.sect_war.challenge(a, sect_b.name, 10, "challenge-a")
    )
    assert war.status == "待应战"
    started = asyncio.run(services.core.sect_war.accept_and_start(b, "accept-b"))

    assert started.status in {"已结算", "战斗中", "已锁定"}
    assert started.report_id
    for user_id in (a, b):
        sections = asyncio.run(services.features.zhanbao.my_report_sections(user_id))
        assert sections.sect
    # 正式战开战即消耗个人待战阵法。
    assert asyncio.run(services.core.formation.prepared(a)) is None
    assert asyncio.run(services.core.formation.prepared(b)) is None


