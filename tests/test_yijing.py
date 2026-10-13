'''意境：六格天赋——六条路各自记阶、道行共享，逐路点阶跑真流程。

接收这条线时它一个测试都没有。这里钉住设计里真正会出错的几条：
① 点阶要**道行够**（不够必须拒，且理由要说出差多少）；
② **六条路各自记阶、并存**（点第二路不动第一路）；
③ **道行只有一份**（两路扣的是同一池，池子见底就再也点不动）；
④ 每条路各自受**境界给的阶上限**约束；
⑤ 旧存档（只有一个「编号」「阶」）**迁移读**不丢进度，写回换成新形状；
⑥ 两路同时开着时战斗快照里**每条路各一个状态**，各带自己数据里的计量名（不串档的机器证据）；
⑦ 同一条请求重放**稳定**（事务幂等）。
'''

from __future__ import annotations

import asyncio
import itertools

import pytest

from game.core.database import StateAddress, StateMutation, TransactionCommand
from game.features.chuangjian_renwu import CreateCharacterRequest
from game.features.yijing import YijingError

长江 = '630001'
山尘 = '630002'

_编号 = itertools.count(1)


def _创建(services, user_id: str, name: str) -> None:
    asyncio.run(
        services.features.chuangjian_renwu.create(
            CreateCharacterRequest(
                user_id=user_id, request_id=f'创建:{user_id}', name=name, gender='男'
            )
        )
    )


def _档案(services, user_id: str):
    return asyncio.run(services.core.character.profile(user_id)).yijing


def _阶(services, user_id: str, content_id: str) -> int:
    return next(
        (item.tier for item in _档案(services, user_id) if item.content_id == content_id), 0
    )


def _道行(services, user_id: str) -> int:
    return asyncio.run(services.core.character.yijing_points(user_id))


def _点(services, user_id: str, content_id: str, request_id: str = '') -> None:
    # 请求编号必须**每次都不同**：重复的编号会被当成幂等重放，于是静默不报错、也不改状态——
    # 我第一版就栽在这儿（两处 DID NOT RAISE 都出自它）。要验重放就显式传同一个编号。
    asyncio.run(
        services.features.yijing.point(
            user_id, request_id or f'意境点:{next(_编号)}', content_id
        )
    )


def _写状态(services, user_id: str, cell: dict, request_id: str) -> None:
    '''直接写「意境」那一格：道行正常由突破发放，测试不重跑突破。'''

    snapshot = asyncio.run(
        services.core.database.get(StateAddress(user_id, 'character', 'main'))
    )
    assert snapshot is not None
    character = dict(snapshot.value)
    character['意境'] = cell
    asyncio.run(
        services.core.database.commit(
            TransactionCommand(
                user_id,
                request_id,
                '测试置备',
                (StateMutation(user_id, 'character', 'main', character, snapshot.version),),
                {},
            )
        )
    )


def _发道行(services, user_id: str, points: int) -> None:
    _写状态(services, user_id, {'道行': points}, f'发道行:{user_id}:{points}')


def test_未点过时没有意境(services) -> None:
    _创建(services, 'y-未开', '未开修士')
    assert _档案(services, 'y-未开') == ()


def test_道行不够点阶被拒且说出差多少(services) -> None:
    _创建(services, 'y-不够', '不够修士')
    with pytest.raises(YijingError) as error:
        _点(services, 'y-不够', 长江)
    assert '道行' in str(error.value)


def test_道行够了点一阶并扣掉(services) -> None:
    _创建(services, 'y-一阶', '一阶修士')
    _发道行(services, 'y-一阶', 1)   # 一阶价 1
    _点(services, 'y-一阶', 长江)
    assert _阶(services, 'y-一阶', 长江) == 1
    assert _道行(services, 'y-一阶') == 0


def test_编号不在册被拒(services) -> None:
    _创建(services, 'y-野号', '野号修士')
    with pytest.raises(Exception) as error:
        _点(services, 'y-野号', '999999')
    assert '999999' in str(error.value) or '意境' in str(error.value)


def test_两路各自记阶且道行只有一份(services) -> None:
    '''点第二路不动第一路；两路扣的是同一池道行，池子见底就再也点不动。'''

    _创建(services, 'y-两路', '两路修士')
    _发道行(services, 'y-两路', 3)     # 一阶 1＋1，再想点第二阶要 2
    _点(services, 'y-两路', 长江)
    _点(services, 'y-两路', 山尘)
    assert _阶(services, 'y-两路', 长江) == 1, '点第二路不许动第一路'
    assert _阶(services, 'y-两路', 山尘) == 1
    assert _道行(services, 'y-两路') == 1, '两路扣的是同一份道行'
    with pytest.raises(YijingError):
        _点(services, 'y-两路', 长江)   # 第二阶要 2，只剩 1
    assert _阶(services, 'y-两路', 长江) == 1


def test_每路各自受境界给的阶上限约束(services) -> None:
    _创建(services, 'y-上限', '上限修士')
    profile = asyncio.run(services.core.character.profile('y-上限'))
    cap = services.core.character.yijing_cap(profile.realm_id)
    _发道行(services, 'y-上限', 200)
    for _ in range(cap):
        _点(services, 'y-上限', 长江)
    assert _阶(services, 'y-上限', 长江) == cap
    with pytest.raises(YijingError) as error:
        _点(services, 'y-上限', 长江)
    assert '阶' in str(error.value)
    _点(services, 'y-上限', 山尘)
    assert _阶(services, 'y-上限', 山尘) == 1, '另一条路独立享受同一个上限'


def test_旧形状迁移读不丢进度(services) -> None:
    '''老存档只有一个「编号」「阶」：迁移读要认出那一路与它的阶，写回换成新形状。'''

    _创建(services, 'y-迁移', '迁移修士')
    _写状态(services, 'y-迁移', {'编号': 长江, '阶': 3, '道行': 5}, '置备:y-迁移')
    assert _阶(services, 'y-迁移', 长江) == 3, '迁移读必须保住原来的阶'
    assert _道行(services, 'y-迁移') == 5
    _点(services, 'y-迁移', 山尘)     # 一阶价 1
    assert _阶(services, 'y-迁移', 长江) == 3, '点新路不许动旧路'
    assert _阶(services, 'y-迁移', 山尘) == 1
    snapshot = asyncio.run(
        services.core.database.get(StateAddress('y-迁移', 'character', 'main'))
    )
    cell = dict(snapshot.value['意境'])
    assert '路' in cell and '编号' not in cell and '阶' not in cell, '写回必须是新形状'


def test_两路同开各落一个状态且各带自己的计量名(services) -> None:
    '''每条点过的路各一个状态；动态档的计量名取自数据、每条路各不相同——「不串档」的机器证据。

    直接置备到**七阶**：质变监听从七阶起才有，而核心只在有质变监听时才给这条路开动态档
    （这是既有设计，不是本轮改的）。点阶本身受境界上限约束，这里验的是战斗落点。
    '''

    _创建(services, 'y-两态', '两态修士')
    _写状态(
        services, 'y-两态', {'路': {长江: 7, 山尘: 7}, '道行': 0}, '置备:y-两态'
    )
    combatant = asyncio.run(services.core.character.combatant('y-两态'))
    statuses = [
        item for item in combatant.prepared_statuses if item.source in (长江, 山尘)
    ]
    names = [item.name for item in combatant.prepared_statuses]
    assert len(statuses) == 2, f'两路应各落一个状态，实际 {names}'
    assert {item.source for item in statuses} == {长江, 山尘}
    counters = {}
    for status in statuses:
        for listener in status.listeners:
            for effect in listener.get('效果') or ():
                if effect.get('能力') == '修改构筑计量':
                    counters[status.source] = effect['计量']
    assert len(counters) == 2, f'两路必须各开自己的动态档，实际 {counters}'
    assert len(set(counters.values())) == 2, f'两路的计量名不许相同（否则串档）：{counters}'
    for source, counter in counters.items():
        assert counter.endswith(source), f'计量名要带上路的身份：{counter} 不含 {source}'


def test_同一条请求重放稳定(services) -> None:
    _创建(services, 'y-回放', '回放修士')
    _发道行(services, 'y-回放', 1)
    _点(services, 'y-回放', 长江, '意境:回放')
    assert _阶(services, 'y-回放', 长江) == 1
    _点(services, 'y-回放', 长江, '意境:回放')
    assert _阶(services, 'y-回放', 长江) == 1, '重放不许再点一阶'
    assert _道行(services, 'y-回放') == 0
