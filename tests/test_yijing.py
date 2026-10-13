'''意境：六条路各自记阶、道行共享，逐路点阶跑真流程。

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

from game.core.asset import InventoryAdjustment
from game.core.database import (
    LocationMutation,
    StateAddress,
    StateMutation,
    TransactionCommand,
)
from game.core.world import LocationQuery
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


# ── 坐忘（退点）：到坐忘台服一枚忘境丹，六路清零、道行退回已发总额 ──

忘境丹 = "160007"
坐忘台 = "坐忘台"


def _发丹(services, user_id: str, code: str, count: int = 1) -> None:
    plan = asyncio.run(
        services.core.asset.plan_inventory_changes(
            user_id, (InventoryAdjustment(code, "01", count),)
        )
    )
    asyncio.run(
        services.core.database.commit(
            TransactionCommand(
                user_id, f"发丹:{user_id}:{code}:{count}", "测试置备", plan.operations, {}
            )
        )
    )


def _挪到(services, user_id: str, place: str) -> None:
    xy = services.core.world.locate(LocationQuery(location_name=place)).xy
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


def _丹数(services, user_id: str) -> int:
    stacks = asyncio.run(services.core.asset.inventory_stacks(user_id, 忘境丹))
    return sum(stack.quantity for stack in stacks)


def _已发总额(services, user_id: str) -> int:
    """按当前境界的阶上限算已发道行：阶价 1..上限 的累计（突破就是这么发的）。"""

    profile = asyncio.run(services.core.character.profile(user_id))
    cap = services.core.character.yijing_cap(profile.realm_id)
    return sum(services.core.character.yijing_cost(tier) for tier in range(1, cap + 1))


def test_坐忘把六路清零并退回已发道行(services) -> None:
    """两路各一阶、道行已花光：在坐忘台退点后，六路清空、道行回到已发总额、丹被扣掉。"""

    _创建(services, "y-坐忘", "坐忘修士")
    _写状态(
        services, "y-坐忘", {"路": {长江: 1, 山尘: 1}, "道行": 0}, "置备:y-坐忘"
    )
    _发丹(services, "y-坐忘", 忘境丹)
    _挪到(services, "y-坐忘", 坐忘台)
    result = asyncio.run(services.features.yijing.refund("y-坐忘", "坐忘:1"))
    assert _档案(services, "y-坐忘") == (), "六路必须全清"
    assert _道行(services, "y-坐忘") == _已发总额(services, "y-坐忘"), "道行要退回已发总额"
    assert _丹数(services, "y-坐忘") == 0, "忘境丹要被扣掉"
    assert "不尽长江意境" in result.before and "山不让尘意境" in result.before, result.before
    assert result.medicine == "忘境丹", result.medicine
    assert result.replayed is False


def test_坐忘失败时丹和状态都不动(services) -> None:
    """没有丹就被拒，而且**状态一点没变**——这条证明扣丹与退点写在同一笔事务里。"""

    _创建(services, "y-坐忘无丹", "无丹修士")
    _写状态(
        services, "y-坐忘无丹", {"路": {长江: 2}, "道行": 1}, "置备:y-坐忘无丹"
    )
    _挪到(services, "y-坐忘无丹", 坐忘台)
    with pytest.raises(YijingError) as error:
        asyncio.run(services.features.yijing.refund("y-坐忘无丹", "坐忘:无丹"))
    assert "忘境丹" in str(error.value)
    assert _阶(services, "y-坐忘无丹", 长江) == 2, "失败不许动状态"
    assert _道行(services, "y-坐忘无丹") == 1, "失败不许动道行"


def test_坐忘重放不重复扣丹(services) -> None:
    _创建(services, "y-坐忘回放", "回放修士")
    _写状态(
        services, "y-坐忘回放", {"路": {长江: 1}, "道行": 0}, "置备:y-坐忘回放"
    )
    _发丹(services, "y-坐忘回放", 忘境丹, 2)
    _挪到(services, "y-坐忘回放", 坐忘台)
    first = asyncio.run(services.features.yijing.refund("y-坐忘回放", "坐忘:回放"))
    second = asyncio.run(services.features.yijing.refund("y-坐忘回放", "坐忘:回放"))
    assert second.replayed is True
    assert _丹数(services, "y-坐忘回放") == 1, "重放不许再扣一枚丹"
    assert first.points_after == second.points_after


def test_不在坐忘台不能坐忘(services) -> None:
    _创建(services, "y-坐忘别处", "别处修士")
    _写状态(
        services, "y-坐忘别处", {"路": {长江: 1}, "道行": 0}, "置备:y-坐忘别处"
    )
    _发丹(services, "y-坐忘别处", 忘境丹)
    with pytest.raises(YijingError) as error:
        asyncio.run(services.features.yijing.refund("y-坐忘别处", "坐忘:别处"))
    assert "坐忘台" in str(error.value)


def test_没点过意境不必坐忘(services) -> None:
    _创建(services, "y-坐忘空", "空手修士")
    _发丹(services, "y-坐忘空", 忘境丹)
    _挪到(services, "y-坐忘空", 坐忘台)
    with pytest.raises(YijingError) as error:
        asyncio.run(services.features.yijing.refund("y-坐忘空", "坐忘:空"))
    assert "一条都没点过" in str(error.value)


def test_坐忘的成功回执能真的渲染出来(services) -> None:
    """盯住玩家真正看到的那张卡：图标分类要登记、文案键要齐。

    兑换码那次就是只验了返回值、从没渲染卡片，上线才炸在没登记的图标上；这里先把卡渲染一遍。
    """

    from game.cmd.专属.坐忘台 import reply as 坐忘回复
    from launch.adapter.qq_protocol.render import render_qq_message

    _创建(services, "y-坐忘卡", "卡片修士")
    _写状态(services, "y-坐忘卡", {"路": {长江: 1}, "道行": 0}, "置备:y-坐忘卡")
    _发丹(services, "y-坐忘卡", 忘境丹)
    _挪到(services, "y-坐忘卡", 坐忘台)
    result = asyncio.run(services.features.yijing.refund("y-坐忘卡", "坐忘:卡"))
    payload = render_qq_message(坐忘回复.refund_result(services.features.yijing, result))
    content = payload["content"] if isinstance(payload, dict) else str(payload)
    assert "忘境丹" in content, content
    assert "不尽长江意境" in content, content
