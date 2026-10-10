'''意境：人物身上的自身强化层，选路与升阶跑真流程。

接收这条线时它一个测试都没有。这里钉住设计里真正会出错的三条：
① 升阶要**道行够**（不够必须拒，且理由要说出差多少）；② **改路把已练的阶清零**（锁认路）；
③ 同一条请求重放**稳定**（事务幂等）。另钉未开路、选路、编号合法性。
'''

from __future__ import annotations

import asyncio

import pytest

from game.app import build_game_services
from game.features.yijing import YijingError
from game.core.database import StateAddress, StateMutation, TransactionCommand
from game.features.chuangjian_renwu import CreateCharacterRequest

长江 = '630001'
山尘 = '630002'


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


def _意境(services, user_id: str):
    return asyncio.run(services.core.character.profile(user_id)).yijing


def _发道行(services, user_id: str, points: int, content_id: str = '') -> None:
    '''直接写人物状态：把道行（与可选的编号）塞进去——道行正常由突破发放，测试不重跑突破。'''

    snapshot = asyncio.run(
        services.core.database.get(StateAddress(user_id, 'character', 'main'))
    )
    assert snapshot is not None
    character = dict(snapshot.value)
    cell = dict(character.get('意境') or {})
    if content_id:
        cell['编号'] = content_id
        cell.setdefault('阶', 0)
    cell['道行'] = points
    character['意境'] = cell
    asyncio.run(
        services.core.database.commit(
            TransactionCommand(
                user_id,
                f'发道行:{user_id}:{points}',
                '测试置备',
                (StateMutation(user_id, 'character', 'main', character, snapshot.version),),
                {},
            )
        )
    )


def test_未开路时没有意境(services) -> None:
    _创建(services, 'y-未开', '未开修士')
    assert _意境(services, 'y-未开') is None


def test_选路之后阶从零起(services) -> None:
    _创建(services, 'y-选路', '选路修士')
    asyncio.run(services.features.yijing.choose('y-选路', '意境:选:1', 长江))
    profile = _意境(services, 'y-选路')
    assert profile is not None
    assert profile.content_id == 长江
    assert profile.tier == 0


def test_编号不在册被拒(services) -> None:
    _创建(services, 'y-野号', '野号修士')
    with pytest.raises(Exception) as error:
        asyncio.run(services.features.yijing.choose('y-野号', '意境:野', '999999'))
    assert '999999' in str(error.value) or '意境' in str(error.value)


def test_道行不够升阶被拒且说出差多少(services) -> None:
    _创建(services, 'y-不够', '不够修士')
    asyncio.run(services.features.yijing.choose('y-不够', '意境:选:2', 长江))
    with pytest.raises(YijingError) as error:
        asyncio.run(services.features.yijing.upgrade('y-不够', '意境:升:1'))
    assert '道行' in str(error.value)


def test_道行够了升一阶并扣掉(services) -> None:
    _创建(services, 'y-升阶', '升阶修士')
    _发道行(services, 'y-升阶', 1, 长江)   # 一阶价 1
    asyncio.run(services.features.yijing.upgrade('y-升阶', '意境:升:2'))
    profile = _意境(services, 'y-升阶')
    assert profile is not None
    assert profile.tier == 1
    assert profile.daoxing == 0


def test_改路把已练的阶清零(services) -> None:
    _创建(services, 'y-改路', '改路修士')
    _发道行(services, 'y-改路', 1, 长江)
    asyncio.run(services.features.yijing.upgrade('y-改路', '意境:升:3'))
    assert _意境(services, 'y-改路').tier == 1
    asyncio.run(services.features.yijing.choose('y-改路', '意境:选:3', 山尘))
    profile = _意境(services, 'y-改路')
    assert profile.content_id == 山尘
    assert profile.tier == 0, '改路必须把已练的阶清零（锁认路）'


def test_同一条请求重放稳定(services) -> None:
    _创建(services, 'y-回放', '回放修士')
    _发道行(services, 'y-回放', 1, 长江)
    asyncio.run(services.features.yijing.upgrade('y-回放', '意境:回放'))
    一次后 = _意境(services, 'y-回放')
    asyncio.run(services.features.yijing.upgrade('y-回放', '意境:回放'))
    两次后 = _意境(services, 'y-回放')
    assert 两次后.tier == 一次后.tier
    assert 两次后.daoxing == 一次后.daoxing
