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
