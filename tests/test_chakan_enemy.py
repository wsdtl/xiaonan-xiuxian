"""查看敌人：编号写法与名字写法都要认，且一律拿真编号做句柄。

判据（tools/基准/说明.md）：显示用中文、隐式受理 id、id 原汁原味。
这一条钉住的是曾经的违反：只看 6 位数字，于是按钮标签上的中文名发不出来。
"""

from __future__ import annotations


def test_enemy_query_accepts_number_and_name(services) -> None:
    feature = services.features.chakan_wupin
    pairs = dict(services.core.data.entity_fields('敌人', ['编号']))
    assert pairs, '库里没有敌人定义'
    name = next(iter(sorted(pairs)))
    number = str(pairs[name]['编号'])

    identifiers = feature.enemy_identifiers()
    assert number in identifiers, f'编号写法不认：{number}'
    assert name in identifiers, f'名字写法不认：{name}'

    by_number = feature.inspect_enemy(number)
    by_name = feature.inspect_enemy(name)
    assert by_number is not None and by_name is not None
    assert by_number.item_id == number, '按编号查要拿真编号'
    assert by_name.item_id == number, '按名字查也要拿真编号（不是把查询串当编号）'
    assert by_number.name == by_name.name == name
    assert feature.inspect_enemy('不存在的敌人') is None
