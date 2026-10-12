"""查看敌人：编号写法与名字写法都要认，且一律拿真编号做句柄。

判据（tools/基准/说明.md）：显示用中文、隐式受理 id、id 原汁原味。
敌人池现在是编号实体池，成员键就是编号，名字在定义的「名称」字段里。
"""

from __future__ import annotations


def test_enemy_query_accepts_number_and_name(services) -> None:
    feature = services.features.chakan_wupin
    rows = dict(services.core.data.entity_fields('敌人', ['编号', '名称']))
    assert rows, '库里没有敌人定义'
    key = next(iter(sorted(rows)))
    name = str(rows[key].get('名称') or key)
    number = str(rows[key]['编号'])

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
