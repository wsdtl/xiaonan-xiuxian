"""探险结算页的联动：按敌人名字查到定义编号，才能把名字做成按钮。

判据第五条：名字只作显示、句柄一律用编号。查不到就返回空串，
前端据此照旧印名字而不硬造句柄；玩家与道侣本来就查不到，落这里。
"""

from __future__ import annotations


def test_exploration_enemy_number_lookup(services) -> None:
    feature = services.features.tanxian
    rows = dict(services.core.data.entity_fields('敌人', ['编号', '名称']))
    assert rows, '库里没有敌人定义'
    key = next(iter(sorted(rows)))
    name = str(rows[key].get('名称') or key)
    number = str(rows[key]['编号'])

    assert feature.enemy_number(name) == number, '按名字查编号，这是联动按钮的句柄来源'
    assert feature.enemy_number('没有这个敌人') == '', '查不到要给空串，让前端照旧印名字'
    assert feature.enemy_number('') == '', '空名字给空串'
    assert feature.enemy_number('P:某玩家') == '', '玩家不是敌人，要空串（道侣同理）'


# ── 「随时可停」的回归：探险按跑完的场次发、讨伐按打完的血段发（2026-10） ──


def test_探险随时可停_按跑完的场次发(services) -> None:
    """结束不再等满排定的时间：已跑完的场次照发，没跑完的那几场不发；状态立刻释放。"""

    import asyncio
    from datetime import datetime, timedelta, timezone

    from game.features.chuangjian_renwu.contracts import CreateCharacterRequest
    from game.features.xinglu.contracts import TravelRequest

    user = 'P:早停探险'
    asyncio.run(
        services.features.chuangjian_renwu.create(
            CreateCharacterRequest(
                user_id=user, request_id='创建:早停探险', name='早停修士', gender='男'
            )
        )
    )
    asyncio.run(
        services.features.xinglu.travel(
            TravelRequest(user_id=user, request_id='挪:早停探险', destination='玉泉涧')
        )
    )
    feature = services.features.tanxian
    asyncio.run(feature.start(user, '始:早停探险'))
    view = asyncio.run(feature.progress(user))
    value = asyncio.run(feature.settle(user, '结:早停探险'))
    assert value.early is True, '立刻结束就是提前结束，不许报「尚未结束」'
    assert value.battle_count == 0, '一场都没跑完就不发场次'
    assert value.total_battles == view.total_battles, '总场数要报出来，卡片才写得出 N/M'
    assert value.total_spirit_stones == 0 and value.total_item_quantity == 0
    # 状态释放了才能立刻再开——这就是「随时可以停」的实测口径
    asyncio.run(feature.start(user, '再始:早停探险'))
    later = asyncio.run(
        feature.settle(
            user, '再结:早停探险', now=datetime.now(timezone.utc) + timedelta(hours=3)
        )
    )
    assert later.early is False, '跑满走完整结算，与原来一致'
    assert later.battle_count == later.total_battles


def test_讨伐随时可停_按打完的血段发(services) -> None:
    """讨伐按已打完的血段发赏：立刻结束一段没打完＝什么都不发；45 秒＝1/3 段。"""

    import asyncio
    from datetime import datetime, timedelta, timezone

    from game.features.chuangjian_renwu.contracts import CreateCharacterRequest
    from game.features.xinglu.contracts import TravelRequest

    feature = services.features.taofa
    user = 'P:早停讨伐'
    asyncio.run(
        services.features.chuangjian_renwu.create(
            CreateCharacterRequest(
                user_id=user, request_id='创建:早停讨伐', name='讨伐修士', gender='男'
            )
        )
    )
    asyncio.run(
        services.features.xinglu.travel(
            TravelRequest(user_id=user, request_id='挪:早停讨伐', destination='镇北军镇')
        )
    )
    now = datetime.now(timezone.utc)
    asyncio.run(feature.start(user, '始:早停讨伐'))
    zero = asyncio.run(feature.settle(user, '结零:早停讨伐', now=now + timedelta(seconds=5)))
    assert zero.early is True
    assert zero.completed_phases == 0 and zero.total_phases == 3, '一段没打完就是 0/3'

    user2 = 'P:早停讨伐二'
    asyncio.run(
        services.features.chuangjian_renwu.create(
            CreateCharacterRequest(
                user_id=user2, request_id='创建:早停讨伐二', name='讨伐修士二', gender='男'
            )
        )
    )
    asyncio.run(
        services.features.xinglu.travel(
            TravelRequest(user_id=user2, request_id='挪:早停讨伐二', destination='镇北军镇')
        )
    )
    asyncio.run(feature.start(user2, '始:早停讨伐二'))
    part = asyncio.run(
        feature.settle(user2, '结一:早停讨伐二', now=now + timedelta(seconds=45))
    )
    assert part.early is True
    assert part.completed_phases == 1 and part.total_phases == 3, '45 秒＝打完 1/3 段'

    user3 = 'P:早停讨伐三'
    asyncio.run(
        services.features.chuangjian_renwu.create(
            CreateCharacterRequest(
                user_id=user3, request_id='创建:早停讨伐三', name='讨伐修士三', gender='男'
            )
        )
    )
    asyncio.run(
        services.features.xinglu.travel(
            TravelRequest(user_id=user3, request_id='挪:早停讨伐三', destination='镇北军镇')
        )
    )
    asyncio.run(feature.start(user3, '始:早停讨伐三'))
    full = asyncio.run(
        feature.settle(user3, '结满:早停讨伐三', now=now + timedelta(hours=3))
    )
    assert full.early is False, '打满走完整结算，与原来一致'


def test_活动卡片把人物与道侣分开数(services) -> None:
    """卡片上三个数必须对得上：人物 = 单位数 − 道侣数；独行时道侣数为 0（不印那一栏）。"""

    import asyncio

    from game.core.asset import InventoryAdjustment
    from game.core.database import TransactionCommand
    from game.features.chuangjian_renwu.contracts import CreateCharacterRequest
    from game.features.daolv_jiejiao.contracts import (
        CompanionGiftRequest,
        CompanionInvitationRequest,
    )
    from game.features.xinglu.contracts import TravelRequest

    def 造(名字, 带道侣, 终点):
        用户 = 'P:' + 名字
        asyncio.run(
            services.features.chuangjian_renwu.create(
                CreateCharacterRequest(
                    user_id=用户, request_id='建:' + 名字, name=名字, gender='男'
                )
            )
        )
        if 带道侣:
            asyncio.run(
                services.features.xinglu.travel(
                    TravelRequest(user_id=用户, request_id='丹:' + 名字, destination='丹霞城')
                )
            )
            plan = asyncio.run(
                services.core.asset.plan_inventory_changes(
                    用户, (InventoryAdjustment('200023', '01', 12),)
                )
            )
            asyncio.run(
                services.core.database.commit(
                    TransactionCommand(
                        用户, '花:' + 名字, '测试', tuple(plan.operations), {'物品': '200023'}
                    )
                )
            )
            for index in range(12):
                asyncio.run(
                    services.features.daolv_jiejiao.gift(
                        CompanionGiftRequest(
                            用户, f'礼{index}:' + 名字, '谢若棠', '200023', '01', 1
                        )
                    )
                )
            asyncio.run(
                services.features.daolv_jiejiao.invite(
                    CompanionInvitationRequest(用户, '邀:' + 名字, '谢若棠')
                )
            )
        if 终点:
            asyncio.run(
                services.features.xinglu.travel(
                    TravelRequest(user_id=用户, request_id='去:' + 名字, destination=终点)
                )
            )
        return 用户

    # 独行：一个玩家、一个人物、没有道侣
    独 = 造('独行修士', False, '玉泉涧')
    v = asyncio.run(services.features.tanxian.start(独, '探:独'))
    assert (v.participant_count, v.formal_unit_count, v.companion_count) == (1, 1, 0)

    # 带道侣：还是一个玩家，但单位数 2 —— 拆开就是「人物 1 ＋ 道侣 1」
    侣 = 造('带侣修士', True, '玉泉涧')
    v = asyncio.run(services.features.tanxian.start(侣, '探:侣'))
    assert (v.participant_count, v.formal_unit_count, v.companion_count) == (1, 2, 1)
    assert v.formal_unit_count - v.companion_count == 1, '人物数不能被道侣顶高'

    # 重放（同一条开始命令再发一次）也必须带上道侣数——这里真出过缺口：
    # 重放走的是另一条构造路径，没带新字段时卡片会少印「同行道侣」。
    重放 = asyncio.run(services.features.tanxian.start(侣, '探:侣'))
    assert 重放.replayed is True
    assert 重放.companion_count == 1, '重放丢了道侣数'

    拽子 = 造('闭关带侣', True, '玉泉涧')
    v = asyncio.run(services.features.biguan.start(拽子, '闭:侣'))
    assert v.companion_count == 1 and v.formal_character_count == 2
    重放闭 = asyncio.run(services.features.biguan.start(拽子, '闭:侣'))
    assert 重放闭.companion_count == 1, '重放丢了道侣数'

    采侣 = 造('采药带侣', True, '')
    v = asyncio.run(services.features.caiyao.start(采侣, '药:侣'))
    assert v.companion_count == 1 and v.gathering_unit_count == 2