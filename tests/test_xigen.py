'''洗根：特殊丹一律绑定地点使用，这条测试跑真流程。

钉三件事：① 重掷出来的根性仍然合法（完整五项、合计一百）；② 掷出来跟原来不一样；
③ **同一条请求重放必须掷出同一副**（事务幂等，不能靠随机性蒙混）。另钉两条拒绝路径。
'''

from __future__ import annotations

import asyncio

import pytest

from game.app import build_game_services
from game.core.asset import InventoryAdjustment
from game.core.database import LocationMutation, TransactionCommand
from game.core.world import LocationQuery
from game.features.chuangjian_renwu import CreateCharacterRequest
from game.features.xigen import XigenError

归元观 = '归元观'
灵根重铸丹 = '160006'
五属性 = {'木', '火', '土', '金', '水'}


@pytest.fixture
def services():
    value = build_game_services()
    try:
        yield value
    finally:
        value.core.database.close()


def _创建(services, user_id: str, name: str) -> None:
    asyncio.run(
        services.features.chuangjian_renwu.create(
            CreateCharacterRequest(
                user_id=user_id, request_id=f'创建:{user_id}', name=name, gender='男'
            )
        )
    )


def _发丹(services, user_id: str, code: str, count: int = 1) -> None:
    plan = asyncio.run(
        services.core.asset.plan_inventory_changes(
            user_id, (InventoryAdjustment(code, '01', count),)
        )
    )
    asyncio.run(
        services.core.database.commit(
            TransactionCommand(user_id, f'发丹:{user_id}:{code}:{count}', '测试置备', plan.operations, {})
        )
    )


def _挪到(services, user_id: str, place: str) -> None:
    xy = services.core.world.locate(LocationQuery(location_name=place)).xy
    current = asyncio.run(services.core.location.current(user_id))
    asyncio.run(
        services.core.database.commit(
            TransactionCommand(
                user_id,
                f'挪:{user_id}:{place}',
                '测试置备',
                (LocationMutation(user_id, xy, current.version),),
                {},
            )
        )
    )


def _根性(services, user_id: str) -> dict:
    return dict(asyncio.run(services.core.character.profile(user_id)).five_elements)


def _备好(services, user_id: str, name: str, count: int = 1) -> None:
    _创建(services, user_id, name)
    _发丹(services, user_id, 灵根重铸丹, count)
    _挪到(services, user_id, 归元观)


def test_洗根产出合法且与原来不同(services) -> None:
    _备好(services, 'x-洗根', '洗根修士')
    before = _根性(services, 'x-洗根')
    result = asyncio.run(services.features.xigen.change('x-洗根', '洗根:x1'))
    after = _根性(services, 'x-洗根')
    assert set(after) == 五属性, after
    assert abs(sum(after.values()) - 100) < 1e-6, after
    assert after != before, after
    assert result.before and result.after


def test_同一条请求重放掷出同一副(services) -> None:
    _备好(services, 'x-回放', '回放修士', count=2)
    first = asyncio.run(services.features.xigen.change('x-回放', '洗根:x回放'))
    一次后 = _根性(services, 'x-回放')
    second = asyncio.run(services.features.xigen.change('x-回放', '洗根:x回放'))
    assert second.replayed is True
    assert second.after == first.after
    assert _根性(services, 'x-回放') == 一次后


def test_换一条请求才是新的一掷(services) -> None:
    _备好(services, 'x-再掷', '再掷修士', count=3)
    掷出的 = []
    for index in range(3):
        asyncio.run(services.features.xigen.change('x-再掷', f'洗根:x第{index}次'))
        掷出的.append(tuple(sorted(_根性(services, 'x-再掷').items())))
    assert len(set(掷出的)) >= 2, 掷出的


def test_不在归元观被拒(services) -> None:
    _创建(services, 'x-别处', '别处修士')
    _发丹(services, 'x-别处', 灵根重铸丹)
    with pytest.raises(XigenError) as error:
        asyncio.run(services.features.xigen.change('x-别处', '洗根:x2'))
    assert '归元观' in str(error.value)


def test_没有丹被拒(services) -> None:
    _创建(services, 'x-无丹', '无丹修士')
    _挪到(services, 'x-无丹', 归元观)
    with pytest.raises(XigenError) as error:
        asyncio.run(services.features.xigen.change('x-无丹', '洗根:x3'))
    assert '灵根重铸丹' in str(error.value)
