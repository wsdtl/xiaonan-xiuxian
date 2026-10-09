"""返本还元：特殊丹一律绑定地点使用，这条测试跑**真流程**。

为什么要有它：特殊丹的绑定写在**世界数据**里（`功能配置.<功能>.丹药`），
而「声明了」不等于「跑得通」——这里在**临时数据库**里造一个人、发一枚丹、把他挪到太素坊，
真的换一次种族，并核对三件事：种族变了、寿元上限按新种族重算、年龄不越界。

顺手钉住三条拒绝路径：不在太素坊、纳戒没有丹、已经是该族。
"""

from __future__ import annotations

import asyncio

import pytest

from game.app import build_game_services
from game.core.asset import InventoryAdjustment
from game.core.database import LocationMutation, TransactionCommand
from game.features.chuangjian_renwu import CreateCharacterRequest
from game.features.fanben import FanbenError

太素坊 = "太素坊"
万化易形丹 = "160005"
人族 = "人族"
秤灵 = "秤灵"


@pytest.fixture
def services():
    value = build_game_services()
    try:
        yield value
    finally:
        value.core.database.close()


def _创建(services, user_id: str, name: str, race: str = "") -> None:
    asyncio.run(
        services.features.chuangjian_renwu.create(
            CreateCharacterRequest(
                user_id=user_id,
                request_id=f"创建:{user_id}",
                name=name,
                gender="男",
                race=race,
            )
        )
    )


def _发丹(services, user_id: str, code: str) -> None:
    plan = asyncio.run(
        services.core.asset.plan_inventory_changes(
            user_id, (InventoryAdjustment(code, "01", 1),)
        )
    )
    asyncio.run(
        services.core.database.commit(
            TransactionCommand(user_id, f"发丹:{user_id}:{code}", "测试置备", plan.operations, {})
        )
    )


def _挪到(services, user_id: str, place: str) -> None:
    xy = services.core.world.locate(
        __import__("game.core.world", fromlist=["LocationQuery"]).LocationQuery(location_name=place)
    ).xy
    current = asyncio.run(services.core.location.current(user_id))
    asyncio.run(
        services.core.database.commit(
            TransactionCommand(
                user_id,
                f"挪:{user_id}:{place}",
                "测试置备",
                (LocationMutation(user_id, xy, current.version),),
                {},
            )
        )
    )


def _种族(services, user_id: str) -> str:
    return asyncio.run(services.core.character.profile(user_id)).race


def test_在太素坊换种族成功且上限与年龄自洽(services) -> None:
    # 新人物默认就是人族，而返本还元丹通向人族——所以要造一个**非人族**才走得通这条路径。
    _创建(services, "u-返本", "换族修士", race=秤灵)
    _发丹(services, "u-返本", 万化易形丹)
    _挪到(services, "u-返本", 太素坊)
    前 = asyncio.run(services.core.character.profile("u-返本"))
    asyncio.run(services.features.fanben.change("u-返本", "返本:1", 人族))
    后 = asyncio.run(services.core.character.profile("u-返本"))
    assert 后.race == 人族, 后.race
    assert 后.age <= 后.lifespan, (后.age, 后.lifespan)
    assert 后.lifespan == round(前.lifespan / services.core.character.race_lifespan_factor(前.race) * services.core.character.race_lifespan_factor(人族))


def test_不在太素坊被拒(services) -> None:
    _创建(services, "u-别处", "别处修士")
    _发丹(services, "u-别处", 万化易形丹)
    with pytest.raises(FanbenError) as error:
        asyncio.run(services.features.fanben.change("u-别处", "返本:2", 人族))
    assert "太素坊" in str(error.value)


def test_没有丹被拒(services) -> None:
    _创建(services, "u-无丹", "无丹修士", race=秤灵)
    _挪到(services, "u-无丹", 太素坊)
    with pytest.raises(FanbenError) as error:
        asyncio.run(services.features.fanben.change("u-无丹", "返本:3", 人族))
    assert "万化易形丹" in str(error.value)


def test_已经是该族被拒(services) -> None:
    # 默认种族就是人族，直接就是目标种族。
    _创建(services, "u-同族", "同族修士")
    _发丹(services, "u-同族", 万化易形丹)
    _挪到(services, "u-同族", 太素坊)
    with pytest.raises(FanbenError) as error:
        asyncio.run(services.features.fanben.change("u-同族", "返本:5", 人族))
    assert "已经" in str(error.value)
