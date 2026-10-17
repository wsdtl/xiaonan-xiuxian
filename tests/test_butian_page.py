'''补天看板：把「补得了」那条分支也用真核心跑通。

页面自己不判规则，所以这里钉的是两件事：① 核心说能补时，只读口如实给出「可补正 + 合法丹」；
② 没公开网页资源的人，站点一律拒绝（连名字都不列）。

为了让核心真的说「能补」，测试按核心自己的判据挑丹再种状态——用的是核心同一个函数，不是我自己编的规则。
'''

from __future__ import annotations

import asyncio


from game.core.database import StateAddress, StateMutation, TransactionCommand
from game.features.chuangjian_renwu import CreateCharacterRequest


def _创建(services, user_id: str, name: str) -> None:
    asyncio.run(
        services.features.chuangjian_renwu.create(
            CreateCharacterRequest(
                user_id=user_id, request_id=f'创建:{user_id}', name=name, gender='男'
            )
        )
    )


def _境界与突破丹(services):
    '''挑一组能让核心认可的组合：记录里那枚给不出永久属性（纯节点），补正那枚只给一项。'''

    service = services.core.character
    realms = [r for r in services.core.data.entities('境界')]
    medicines = [m for m in services.core.data.entities('丹药') if str(m).startswith('14')]
    for realm_id in realms:
        for record_medicine in medicines:
            try:
                _, original = service._breakthrough_medicine(record_medicine, realm_id)
            except Exception:
                continue
            if original:
                continue
            for source in medicines:
                try:
                    _, permanent = service._breakthrough_medicine(source, realm_id)
                except Exception:
                    continue
                if len(permanent) == 1:
                    return realm_id, record_medicine, source
    raise AssertionError('数据库里找不到一组可用于测试的突破丹')


def _种(services, user_id: str, realm_id: str, record_medicine: str) -> None:
    '''直接写人物状态：把境界与突破记录置成一组，测试不重跑突破流程。'''

    snapshot = asyncio.run(
        services.core.database.get(StateAddress(user_id, 'character', 'main'))
    )
    character = dict(snapshot.value)
    character['境界'] = realm_id
    character['突破记录'] = [
        {'目标境界': realm_id, '突破丹': record_medicine, '补正来源丹药': ''}
    ]
    asyncio.run(
        services.core.database.commit(
            TransactionCommand(
                user_id, f'种记录:{user_id}', '测试置备',
                (StateMutation(user_id, 'character', 'main', character, snapshot.version),),
                {},
            )
        )
    )


def test_核心说能补时只读口如实给出(services) -> None:
    _创建(services, 'b-可补', '可补修士')
    realm_id, record_medicine, source = _境界与突破丹(services)
    _种(services, 'b-可补', realm_id, record_medicine)
    记录里的丹 = services.core.data.entity('丹药', record_medicine)['名称']
    补正丹 = services.core.data.entity('丹药', source)['名称']
    _发丹(services, 'b-可补', source)
    value = asyncio.run(services.features.butian.page('b-可补'))
    人物 = [t for t in value['targets'] if t['kind'] == '人物'][0]
    assert 人物['correctable'] is True, f"核心应当认可：{人物['reason']}"
    assert source in [row['id'] for row in 人物['legal']]
    realm_name = services.core.data.entity('境界', realm_id)['名称']
    assert 人物['realm'] == realm_name
    assert value['ui']['标题']
    assert any(m['id'] == source for m in value['candidates']), '补正丹要在候选里'


def _发丹(services, user_id: str, medicine_id: str) -> None:
    from game.core.asset import InventoryAdjustment
    plan = asyncio.run(
        services.core.asset.plan_inventory_changes(
            user_id, (InventoryAdjustment(medicine_id, '01', 1),)
        )
    )
    asyncio.run(
        services.core.database.commit(
            TransactionCommand(
                user_id, f'发丹:{user_id}', '测试置备', plan.operations, {},
            )
        )
    )


def test_没公开的人读不到(services, monkeypatch) -> None:
    import importlib
    site = importlib.import_module('game.cmd.特殊地点.裂天原.site')
    monkeypatch.setattr(site, 'current_game_services', lambda: services)
    # 先让清单里有人：不然会走「一个人都没公开」那条早返回，测不到拒绝分支。
    _创建(services, 'b-公开', '公开修士')
    asyncio.run(services.features.wangye.set_public('b-公开', '网页:测试', True))
    response = asyncio.run(site.butian_data('user:根本不存在的编号'))
    assert response.status_code == 400
    assert b'\xe6\xb2\xa1\xe6\x9c\x89\xe5\x85\xac\xe5\xbc\x80' in response.body, '拒绝时要说「没有公开网页资源」'
