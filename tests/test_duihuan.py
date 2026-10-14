'''兑换码：码在 JSON 里，玩家报码换发放，一次兑换一笔事务。

钉八件事：① 码不在册或已用回同一句（不泄露码表）；② 每人限次落在**人物状态**里，不是请求编号；
③ 发放真的到手（灵石进钱包、物品进纳戒）；④ 一次兑换只落**一笔**事务；⑤ 同一条请求重放稳定；
⑥ 回执**写出物品名**（不再是「物品×N」）；⑦ 随机发放只发候选池里的东西；⑧ 同一个随机码不同玩家各抽各的。

**测试不抄码面与数量**：委托方会改新手码的码面（已从 `KAIFU2026` 改成 `2026`）与发放值，
所以这里一律从 `data/玩法/兑换码/内容/兑换码.json` 现读——测试钉的是行为，不是数据快照。
'''

from __future__ import annotations

import asyncio

import pytest

from game.core.database import StateAddress
from game.features.chuangjian_renwu import CreateCharacterRequest
from game.features.duihuan import DuihuanError

新手编号 = '640001'
随机码编号 = '640009'   # VIP888：带一个随机候选池


def _创建(services, user_id: str, name: str) -> None:
    asyncio.run(
        services.features.chuangjian_renwu.create(
            CreateCharacterRequest(
                user_id=user_id, request_id=f'创建:{user_id}', name=name, gender='男'
            )
        )
    )


def _码(services, code_id: str) -> str:
    '''从数据里读码面：委托方会改它，测试不该跟着改。'''

    return str(services.core.data.entities('兑换码')[code_id]['码'])


def _发放(services, code_id: str) -> list[dict]:
    return list(services.core.data.entities('兑换码')[code_id]['发放'])


def _灵石发放(services, code_id: str) -> int:
    return sum(
        int(item.get('数量') or 0)
        for item in _发放(services, code_id)
        if item.get('类型') == '灵石'
    )


def _状态(services, user_id: str) -> dict:
    snapshot = asyncio.run(
        services.core.database.get(StateAddress(user_id, 'character', 'main'))
    )
    return dict(snapshot.value)


def test_兑换成功且发放到手(services) -> None:
    _创建(services, 'd-成功', '兑换修士')
    开服码 = _码(services, 新手编号)
    前 = _状态(services, 'd-成功')
    result = asyncio.run(services.features.duihuan.redeem('d-成功', '兑换:1', 开服码))
    后 = _状态(services, 'd-成功')
    assert result.code == 开服码
    assert result.code_id == 新手编号
    assert 后['灵石'] == 前['灵石'] + _灵石发放(services, 新手编号), '灵石要真的进钱包'
    assert 新手编号 in list(后.get('已兑换码') or []), '兑换记录要落在人物状态里'
    stacks = asyncio.run(services.core.asset.inventory_stacks('d-成功', '100001'))
    assert stacks, '物品要真的进纳戒（清心散）'


def test_回执写出物品名(services) -> None:
    '''回执只写「物品×10」时玩家不知道拿到了什么；十个码之后这条必须有。'''

    _创建(services, 'd-名字', '名字修士')
    result = asyncio.run(
        services.features.duihuan.redeem('d-名字', '兑换:名字', _码(services, 新手编号))
    )
    assert '清心散' in result.granted, '回执要写物品名'
    assert '物品×' not in result.granted, '不该再出现没有名字的「物品×N」'


def test_同一个码第二次被拒(services) -> None:
    _创建(services, 'd-二次', '二次修士')
    开服码 = _码(services, 新手编号)
    asyncio.run(services.features.duihuan.redeem('d-二次', '兑换:2a', 开服码))
    with pytest.raises(DuihuanError) as error:
        asyncio.run(services.features.duihuan.redeem('d-二次', '兑换:2b', 开服码))
    assert '用过了' in str(error.value)


def test_码不在册与已用回同一句(services) -> None:
    _创建(services, 'd-野码', '野码修士')
    开服码 = _码(services, 新手编号)
    with pytest.raises(DuihuanError) as error:
        asyncio.run(services.features.duihuan.redeem('d-野码', '兑换:3', 'MEIYOUZHEGEMA'))
    不在册 = str(error.value)
    asyncio.run(services.features.duihuan.redeem('d-野码', '兑换:3b', 开服码))
    with pytest.raises(DuihuanError) as error2:
        asyncio.run(services.features.duihuan.redeem('d-野码', '兑换:3c', 开服码))
    已用过 = str(error2.value)
    assert '无效' in 不在册
    assert 开服码 not in 不在册 and 开服码 not in 已用过


def test_码不区分大小写与首尾空白(services) -> None:
    _创建(services, 'd-大小写', '大小写修士')
    开服码 = _码(services, 新手编号)
    asyncio.run(services.features.duihuan.redeem('d-大小写', '兑换:4', f'  {开服码.lower()}  '))
    assert 新手编号 in list(_状态(services, 'd-大小写').get('已兑换码') or [])


def test_码格式不对时给格式那句(services) -> None:
    _创建(services, 'd-格式', '格式修士')
    with pytest.raises(DuihuanError) as error:
        asyncio.run(services.features.duihuan.redeem('d-格式', '兑换:5', '有中文的码'))
    assert '大写字母' in str(error.value) or '数字' in str(error.value)


def test_一次兑换只落一笔事务(services) -> None:
    _创建(services, 'd-事务', '事务修士')
    asyncio.run(
        services.features.duihuan.redeem('d-事务', '兑换:6', _码(services, 新手编号))
    )
    committed = asyncio.run(
        services.core.database.committed_transaction('d-事务', '兑换:6')
    )
    assert committed is not None
    assert committed.receipt.business_type == '兑换码', '业务类型应当是「兑换码」，一笔事务管全部发放'


def test_同一条请求重放稳定(services) -> None:
    _创建(services, 'd-回放', '回放修士')
    开服码 = _码(services, 新手编号)
    first = asyncio.run(services.features.duihuan.redeem('d-回放', '兑换:7', 开服码))
    一次后 = _状态(services, 'd-回放')
    second = asyncio.run(services.features.duihuan.redeem('d-回放', '兑换:7', 开服码))
    assert second.replayed is True
    assert _状态(services, 'd-回放')['灵石'] == 一次后['灵石']
    assert first.granted == second.granted


def _候选名字(services, code_id: str) -> set[str]:
    '''这条码的随机候选池里全部物品的名字。'''

    项 = next(item for item in _发放(services, code_id) if item.get('类型') == '随机物品')
    原始 = 项['候选文件']
    # 快照是冻结的：JSON 里的数组在这里是元组，不能只认 list。
    文件 = [原始] if isinstance(原始, str) else list(原始)
    名字: set[str] = set()
    for 名 in 文件:
        分类 = services.core.data.pool_section(str(名))
        for 编号 in services.core.data.pool_members((str(名),), 分类):
            名字.add(services.core.item_catalog.inspect_entity(str(编号)).name)
    return 名字


def test_成功回执能真的渲染出来(services) -> None:
    '''盯住玩家真正看到的那张卡：`icon` 必须是**已登记**的图标分类。

    这条是补的教训——上线第一次兑换就炸在 `KeyError: gift`（`message/icons.py` 的图标表里没有 `gift`），
    而当时的验证只看了 `redeem()` 的返回值、**从没渲染过卡片**：语料与判据走的都是错误路径，到不了成功卡。
    '''

    from game.cmd.通用.兑换码 import reply as 兑换回复
    from launch.adapter.qq_protocol.payload import payload_text
    from launch.adapter.qq_protocol.render import render_qq_message

    _创建(services, 'd-卡片', '卡片修士')
    result = asyncio.run(
        services.features.duihuan.redeem('d-卡片', '兑换:卡片', _码(services, 新手编号))
    )
    document = 兑换回复.result(services.features.duihuan, result)
    payload = render_qq_message(document)
    # markdown 消息的正文在 markdown.content 里（官方要求传了 markdown 后 content 必须为空）。
    content = payload_text(payload)
    assert result.name in content, '卡片上要出现礼包名'
    assert '清心散' in content, '卡片上要出现到手的东西'


def test_随机发放只发候选池里的东西(services) -> None:
    _创建(services, 'd-随机', '随机修士')
    result = asyncio.run(
        services.features.duihuan.redeem('d-随机', '兑换:随机', _码(services, 随机码编号))
    )
    候选 = _候选名字(services, 随机码编号)
    固定 = {
        services.core.item_catalog.inspect_entity(str(item['编号'])).name
        for item in _发放(services, 随机码编号)
        if item.get('类型') == '物品'
    }
    拿到 = {text.split('×')[0] for text in result.granted.split('、')} - {'灵石'}
    assert 拿到 <= 候选 | 固定, f'发放跑出了候选池或固定清单：{sorted(拿到 - 候选 - 固定)}'
    assert 拿到 & 候选, '随机项应当真的从候选池里抽出东西'


def test_同一个随机码不同玩家各抽各的(services) -> None:
    _创建(services, 'd-甲', '甲修士')
    _创建(services, 'd-乙', '乙修士')
    码 = _码(services, 随机码编号)
    甲 = asyncio.run(services.features.duihuan.redeem('d-甲', '兑换:甲', 码))
    乙 = asyncio.run(services.features.duihuan.redeem('d-乙', '兑换:乙', 码))
    assert 甲.granted != 乙.granted, '随机档不同玩家应当各抽各的'
