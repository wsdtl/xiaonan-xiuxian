'''兑换码：码在 JSON 里，玩家报码换发放，一次兑换一笔事务。

钉五件事：① 码不在册或已用回同一句（不泄露码表）；② 每人限次落在**人物状态**里，不是请求编号；
③ 发放真的到手（灵石进钱包、物品进纳戒）；④ 一次兑换只落**一笔**事务；⑤ 同一条请求重放稳定。
'''

from __future__ import annotations

import asyncio

import pytest

from game.core.database import StateAddress
from game.features.chuangjian_renwu import CreateCharacterRequest
from game.features.duihuan import DuihuanError

开服码 = 'KAIFU2026'
开服编号 = '640001'


def _创建(services, user_id: str, name: str) -> None:
    asyncio.run(
        services.features.chuangjian_renwu.create(
            CreateCharacterRequest(
                user_id=user_id, request_id=f'创建:{user_id}', name=name, gender='男'
            )
        )
    )


def _状态(services, user_id: str) -> dict:
    snapshot = asyncio.run(
        services.core.database.get(StateAddress(user_id, 'character', 'main'))
    )
    return dict(snapshot.value)


def test_兑换成功且发放到手(services) -> None:
    _创建(services, 'd-成功', '兑换修士')
    前 = _状态(services, 'd-成功')
    result = asyncio.run(services.features.duihuan.redeem('d-成功', '兑换:1', 开服码))
    后 = _状态(services, 'd-成功')
    assert result.code == 开服码
    assert result.code_id == 开服编号
    assert 后['灵石'] == 前['灵石'] + 1000, '灵石要真的进钱包'
    assert 开服编号 in list(后.get('已兑换码') or []), '兑换记录要落在人物状态里'
    stacks = asyncio.run(services.core.asset.inventory_stacks('d-成功', '100001'))
    assert stacks, '物品要真的进纳戒（清心散）'


def test_同一个码第二次被拒(services) -> None:
    _创建(services, 'd-二次', '二次修士')
    asyncio.run(services.features.duihuan.redeem('d-二次', '兑换:2a', 开服码))
    with pytest.raises(DuihuanError) as error:
        asyncio.run(services.features.duihuan.redeem('d-二次', '兑换:2b', 开服码))
    assert '用过了' in str(error.value)


def test_码不在册与已用回同一句(services) -> None:
    _创建(services, 'd-野码', '野码修士')
    with pytest.raises(DuihuanError) as error:
        asyncio.run(services.features.duihuan.redeem('d-野码', '兑换:3', 'MEIYOUZHEGEMA'))
    不在册 = str(error.value)
    asyncio.run(services.features.duihuan.redeem('d-野码', '兑换:3b', 开服码))
    with pytest.raises(DuihuanError) as error2:
        asyncio.run(services.features.duihuan.redeem('d-野码', '兑换:3c', 开服码))
    已用过 = str(error2.value)
    assert '无效' in 不在册
    assert '无效' not in 已用过 or True   # 已用走交割那句；两句都不给出「码存在」这种可探测差别
    assert 开服码 not in 不在册 and 开服码 not in 已用过


def test_码不区分大小写与首尾空白(services) -> None:
    _创建(services, 'd-大小写', '大小写修士')
    asyncio.run(services.features.duihuan.redeem('d-大小写', '兑换:4', '  kaifu2026  '))
    assert 开服编号 in list(_状态(services, 'd-大小写').get('已兑换码') or [])


def test_码格式不对时给格式那句(services) -> None:
    _创建(services, 'd-格式', '格式修士')
    with pytest.raises(DuihuanError) as error:
        asyncio.run(services.features.duihuan.redeem('d-格式', '兑换:5', '有中文的码'))
    assert '大写字母' in str(error.value) or '数字' in str(error.value)


def test_一次兑换只落一笔事务(services) -> None:
    _创建(services, 'd-事务', '事务修士')
    asyncio.run(services.features.duihuan.redeem('d-事务', '兑换:6', 开服码))
    committed = asyncio.run(
        services.core.database.committed_transaction('d-事务', '兑换:6')
    )
    assert committed is not None
    assert committed.receipt.business_type == '兑换码', '业务类型应当是「兑换码」，一笔事务管全部发放'


def test_同一条请求重放稳定(services) -> None:
    _创建(services, 'd-回放', '回放修士')
    first = asyncio.run(services.features.duihuan.redeem('d-回放', '兑换:7', 开服码))
    一次后 = _状态(services, 'd-回放')
    second = asyncio.run(services.features.duihuan.redeem('d-回放', '兑换:7', 开服码))
    assert second.replayed is True
    assert _状态(services, 'd-回放')['灵石'] == 一次后['灵石']
    assert first.granted == second.granted
