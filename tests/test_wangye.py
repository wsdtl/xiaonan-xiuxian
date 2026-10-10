'''网页公开：一条全局开关，管住所有「网页直接读你的数据」的页面。

钉五件事：① 没人物开不了；② 开了才进 scopes、关了就没了；③ 同一条请求重放稳定；
④ 重复关闭不出第二笔事务；⑤ 装配台读的是**同一条**开关（跨包一致，不各存一份）。
'''

from __future__ import annotations

import asyncio

import pytest

from game.features.chuangjian_renwu import CreateCharacterRequest
from game.features.wangye import WangyeError


def _创建(services, user_id: str, name: str) -> None:
    asyncio.run(
        services.features.chuangjian_renwu.create(
            CreateCharacterRequest(
                user_id=user_id, request_id=f'创建:{user_id}', name=name, gender='男'
            )
        )
    )


def _名字(services) -> list[str]:
    return [scope.name for scope in asyncio.run(services.features.wangye.scopes())]


def test_没有人物开不了开关(services) -> None:
    with pytest.raises(WangyeError):
        asyncio.run(services.features.wangye.set_public('w-无人物', '网页:1', True))


def test_开了才进清单关了就没(services) -> None:
    _创建(services, 'w-开关', '开关修士')
    assert '开关修士' not in _名字(services)
    assert asyncio.run(services.features.wangye.set_public('w-开关', '网页:开', True)) is True
    assert '开关修士' in _名字(services)
    assert asyncio.run(services.features.wangye.set_public('w-开关', '网页:关', False)) is False
    assert '开关修士' not in _名字(services)


def test_同一条请求重放稳定(services) -> None:
    _创建(services, 'w-回放', '回放修士')
    first = asyncio.run(services.features.wangye.set_public('w-回放', '网页:回放', True))
    second = asyncio.run(services.features.wangye.set_public('w-回放', '网页:回放', True))
    assert first is True and second is True
    assert '回放修士' in _名字(services)


def test_重复关闭不落第二笔事务(services) -> None:
    _创建(services, 'w-重复', '重复修士')
    asyncio.run(services.features.wangye.set_public('w-重复', '网页:开2', True))
    asyncio.run(services.features.wangye.set_public('w-重复', '网页:关2', False))
    关之后 = services.core.database.status().transaction_count
    asyncio.run(services.features.wangye.set_public('w-重复', '网页:关3', False))
    assert services.core.database.status().transaction_count == 关之后, '已经是关的，不该再写一笔'


def test_装配台读的是同一条开关(services) -> None:
    _创建(services, 'w-一致', '一致修士')
    装配台 = services.features.zhuangpei
    asyncio.run(services.features.wangye.set_public('w-一致', '网页:一致', True))
    assert 'user:w-一致' in [scope['id'] for scope in asyncio.run(装配台.scopes())]
    asyncio.run(services.features.wangye.set_public('w-一致', '网页:一致关', False))
    assert 'user:w-一致' not in [scope['id'] for scope in asyncio.run(装配台.scopes())]
    with pytest.raises(Exception):
        asyncio.run(装配台.page('user:w-一致'))
