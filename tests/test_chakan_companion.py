"""查看修士：实例的读法本身就带鉴权（判据第六条：鉴权在服务端）。

两个事实（都实测过）：
1. 拿别人的 user_id 去问道侣，永远拿不到实例——companion.instance(user_id, companion_id)
   的第一个参数就是"我"，所以别人的实例天然拒；
2. 空的 user_id 不是"查不到"，而是被字段层当场拒（ValueError），比返回 None 更硬。
"""

from __future__ import annotations

import asyncio

import pytest


def test_companion_lookup_refuses_without_a_relation(services) -> None:
    feature = services.features.weizhi
    companions = services.core.data.entities('道侣')
    assert companions, '库里没有道侣实体'
    ids = sorted(companions)[:3]

    for companion_id in ids:
        assert asyncio.run(feature.inspect_companion('P:从未结交过的人', companion_id)) is None, (
            f'{companion_id}：没有关系却拿到了实例，说明鉴权不在服务端'
        )
        with pytest.raises(ValueError):
            asyncio.run(feature.inspect_companion('', companion_id))
