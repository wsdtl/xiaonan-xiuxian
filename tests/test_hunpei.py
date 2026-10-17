"""婚配求子：玩家 ↔ 玩家，请求住日志库，孩子只进求方族谱。

钉六件事：
① 同性被挡、附近查无此人被挡；
② 请求能被对方看到（待办）；
③ 同意后孩子进求方族谱、被求方族谱为空；
④ 扣丹与胎次各一；
⑤ 重复同意被挡、拒绝不结算；
⑥ 名字要落在**附近可见**的人身上（与送礼、邀约同一套口径）。
"""
from __future__ import annotations

import asyncio

from game.core.asset import InventoryAdjustment
from game.core.database import StateAddress, TransactionCommand
from game.features.chuangjian_renwu import CreateCharacterRequest
from game.features.hunpei import BirthDeniedError, HunpeiError
from game.features.xinglu import TravelRequest


def _创建(services, user_id: str, name: str, gender: str) -> None:
    asyncio.run(
        services.features.chuangjian_renwu.create(
            CreateCharacterRequest(
                user_id=user_id, request_id=f"创建:{user_id}", name=name, gender=gender
            )
        )
    )


def _去医院(services, user_id: str) -> None:
    asyncio.run(
        services.features.xinglu.travel(
            TravelRequest(user_id=user_id, request_id=f"去医院:{user_id}", destination="妇产科医院")
        )
    )


def _给丹(services, user_id: str, count: int) -> None:
    plan = asyncio.run(
        services.core.asset.plan_inventory_changes(
            user_id, (InventoryAdjustment("160008", "01", count),)
        )
    )
    asyncio.run(
        services.core.database.commit(
            TransactionCommand(user_id, f"备丹:{user_id}", "自查", tuple(plan.operations), {})
        )
    )


def _丹数(services, user_id: str) -> int:
    stacks = asyncio.run(services.core.asset.inventory_stacks(user_id, "160008"))
    return sum(int(getattr(stack, "quantity", 0) or 0) for stack in stacks)


def _族谱(services, user_id: str) -> list[dict]:
    xuemai = services.features.xuemai
    snapshot = asyncio.run(
        services.core.database.get(StateAddress(user_id, xuemai.state_type(), xuemai.state_key()))
    )
    value = dict(snapshot.value) if snapshot is not None else {}
    rows = value.get("族谱") or []
    return [dict(row) for row in rows]


def _备好三个人(services, tag: str) -> tuple[str, str, str, str]:
    """同一进程里每个用例各自一套人物：编号与姓名都带 tag，互不干扰。

    返回 (男编号, 女编号, 男二编号, 女姓名)。
    """

    man = f"求子-{tag}-男"
    woman = f"求子-{tag}-女"
    other = f"求子-{tag}-男二"
    man_name, woman_name, other_name = f"求{tag}甲", f"求{tag}乙", f"求{tag}丙"
    _创建(services, man, man_name, "男")
    _创建(services, woman, woman_name, "女")
    _创建(services, other, other_name, "男")
    for user_id in (man, woman, other):
        _去医院(services, user_id)
    _给丹(services, man, 5)
    return man, woman, other, woman_name


def test_同性被挡(services):
    man, _woman, _other, _woman_name = _备好三个人(services, "同性")
    try:
        asyncio.run(services.features.hunpei.ask(man, "求同性丙"))
    except BirthDeniedError as exc:
        assert "一男一女" in str(exc)
    else:
        raise AssertionError("同性求子应当被挡")


def test_附近查无此人被挡(services):
    man, _woman, _other, _woman_name = _备好三个人(services, "查无")
    try:
        asyncio.run(services.features.hunpei.ask(man, "查无此人的名字"))
    except HunpeiError as exc:
        assert "附近" in str(exc)
    else:
        raise AssertionError("附近没有的人也应当被挡")


def test_求子全流程(services):
    man, woman, _other, woman_name = _备好三个人(services, "全流程")
    before = _丹数(services, man)

    ask = asyncio.run(services.features.hunpei.ask(man, woman_name))
    assert ask.target_id == woman
    todo = asyncio.run(services.features.hunpei.pending(woman))
    assert len(todo) == 1 and todo[0].asker_id == man

    respond = asyncio.run(services.features.hunpei.respond(woman, "", True))
    assert respond.agreed and respond.result is not None

    man_rows = _族谱(services, man)
    woman_rows = _族谱(services, woman)
    assert len(man_rows) == 1, "孩子该进求方族谱"
    assert len(woman_rows) == 0, "被求者不留记录"
    child = man_rows[0]
    assert child["父编号"] == man and child["母编号"] == woman, "父母按性别落"
    assert child["DNA"] and len(child["DNA"]) == 12
    assert _丹数(services, man) == before - 1
    assert respond.result.births_this_generation == 1
    assert respond.result.births_limit == services.features.hunpei.limit()

    try:
        asyncio.run(services.features.hunpei.respond(woman, ask.request_id, True))
    except HunpeiError as exc:
        assert "已经处理过" in str(exc)
    else:
        raise AssertionError("重复同意应当被挡")


def test_拒绝不结算(services):
    man, woman, _other, woman_name = _备好三个人(services, "拒绝")
    ask = asyncio.run(services.features.hunpei.ask(man, woman_name))
    refused = asyncio.run(services.features.hunpei.respond(woman, ask.request_id, False))
    assert refused.agreed is False and refused.result is None
    assert _族谱(services, man) == []
    assert _丹数(services, man) == 5
