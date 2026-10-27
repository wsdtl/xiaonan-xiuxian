from __future__ import annotations

import asyncio
import json
from pathlib import Path

from game.core.asset.contracts import CultivationAcquisition
from game.core.character.contracts import CharacterCreateCommand
from game.core.database.contracts import TransactionCommand
from game.features.shiyong import UsePlan, UseRedirect, UseRequest

DATA = Path(__file__).resolve().parents[1] / "data"


def test_use_profiles_cover_every_prefix() -> None:
    numbers = json.loads(
        (DATA / "基础/定义/编号.json").read_text(encoding="utf-8")
    )["编号前缀"]
    rules = json.loads(
        (DATA / "物品/规则/使用.json").read_text(encoding="utf-8")
    )["使用方式"]
    expected = {str(row["前缀"]) for row in numbers}
    actual = {str(row["前缀"]) for row in rules}
    assert actual == expected
    for row in rules:
        assert row["方式"] in {"执行", "重定向", "暂缓", "不可使用"}
        if row["方式"] == "执行":
            assert row["端口"] in {"renwu_peiyang", "xiantian_lingbao", "fudan", "buzhen"}
            assert row["结果"] in {"equip", "forge", "treasure", "medicine", "formation"}
        elif row["方式"] in {"重定向", "暂缓"}:
            assert row["帮助"]


def _seed_card(services, user_id: str) -> None:
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(
                user_id, "create-use-gateway", "网关测试", "男", (15, 17), ""
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
            TransactionCommand(user_id, "seed-use-gateway", "测试置备", plan.operations, {})
        )
    )


def test_gateway_executes_card_and_redirects(services) -> None:
    user_id = "use-gateway-e2e"
    _seed_card(services, user_id)
    gateway = services.features.shiyong

    plan = asyncio.run(
        gateway.plan(UseRequest(user_id, "use-gateway-card", "400001", grade="01"))
    )
    assert isinstance(plan, UsePlan)
    assert [item.value for item in plan.description.candidates] == ["1", "2", "3", "4", "5", "6"]
    result = asyncio.run(gateway.execute(plan, "1"))
    assert result.result.category == "功法"

    breakthrough = asyncio.run(
        gateway.plan(UseRequest(user_id, "use-gateway-break", "140001"))
    )
    assert isinstance(breakthrough, UseRedirect)
    assert [action.command for action in breakthrough.actions] == [
        "帮助 人物突破",
        "帮助 道侣突破",
    ]

    material = asyncio.run(
        gateway.plan(UseRequest(user_id, "use-gateway-material", "200001"))
    )
    assert isinstance(material, UseRedirect)
    assert "炼丹" in [action.label for action in material.actions]

    treasure = asyncio.run(
        gateway.plan(UseRequest(user_id, "use-gateway-treasure", "540001"))
    )
    assert isinstance(treasure, UsePlan)
    assert treasure.description.candidates == ()

    medicine = asyncio.run(
        gateway.plan(UseRequest(user_id, "use-gateway-medicine", "100001"))
    )
    assert isinstance(medicine, UsePlan)
    assert [item.value for item in medicine.description.candidates] == ["人物", "道侣"]

    unavailable = asyncio.run(
        gateway.plan(UseRequest(user_id, "use-gateway-enemy", "300001"))
    )
    assert isinstance(unavailable, UseRedirect)
    assert unavailable.title == "不可使用"
