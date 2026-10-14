"""查看名下道侣的三种提示语：都在文案对象里，「没结交」那条还带编号占位。

判据：文案来自展示数据集（不造词）。这一条钉住三件事：
三条话都在、都没被清空、「没结交」那条带 {编号} 占位——
占位掉了玩家就看不到该去看哪个编号。
"""

from __future__ import annotations


def test_cultivator_copy_is_complete(services) -> None:
    copy = services.features.weizhi.copy()

    for name in ('cultivator_view', 'cultivator_missing', 'cultivator_queriless'):
        value = getattr(copy, name)
        assert isinstance(value, str) and value.strip(), f'{name} 是空的'

    not_met = copy.cultivator_not_met
    assert '{编号}' in not_met, '「没结交」那条要带 {编号} 占位，玩家才知道去看哪个编号'
    assert '查看' in not_met, '「没结交」那条要指路给「查看」'
    rendered = not_met.format_map({'编号': '500002'})
    assert '500002' in rendered, '占位没被替换'
