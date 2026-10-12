"""敌人条目页的判据（第一节）：范围照给、答案 ???。

配置里有的（等级、实力波动、掉落、交锋所得、本命武器）照实；
配置里没有的（种族／性别／器律，是生成期按实例编号抽的）遮成 ??? ——
那不是藏信息，是唯一诚实的写法：配置根本没限定"这一个"是哪个族。
"""

from __future__ import annotations

from game.cmd.通用.查看.items import SectionInput, _enemy_lines


def _entry_of(services, name: str) -> dict:
    entry = dict(services.core.data.entity('敌人', name))
    entry.pop('编号', None)
    return entry


def _has_weapon(services, name: str) -> bool:
    weapon = _entry_of(services, name).get('本命武器')
    return isinstance(weapon, dict) and bool(weapon.get('名称'))


def test_enemy_page_shows_ranges_and_masks_the_drawn_answers(services) -> None:
    pairs = dict(services.core.data.entity_fields('敌人', ['编号']))
    assert pairs, '库里没有敌人定义'
    names = sorted(pairs)
    armed = [n for n in names if _has_weapon(services, n)]
    bare = [n for n in names if not _has_weapon(services, n)]
    for name in names[:12]:
        # 武器那一支是有条件覆盖：配置里有的必须印、没有的不许印；
        # 池里两类都存在（灵兽不带本命武器），但哪一批落在前 12 个不预定。
        entry = _entry_of(services, name)
        lines = _enemy_lines(SectionInput(entry, {}, ()))
        assert lines, f'{name}：一条都没印出来'
        text = chr(10).join(lines)

        # 一、遮住的那三样必须是 ???（配置里没有，就不假装知道）
        assert text.count('???') == 3, f'{name}：种族／性别／器律应当各遮一个 ??? —— {text}'

        # 二、等级是区间，照给（配置里就是 [低, 高]）
        level = entry.get('等级')
        if isinstance(level, list) and len(level) == 2:
            assert f'等级：{level[0]} ~ {level[1]}' in text, f'{name}：等级区间没照给 —— {text}'

        # 三、本命武器：配置里有的照实印，没有的不许编
        weapon = entry.get('本命武器')
        if isinstance(weapon, dict) and weapon.get('名称'):
            assert str(weapon['名称']) in text, f'{name}：配置里有本命武器却没印'
        else:
            assert '阶' not in text, f'{name}：配置里没有本命武器却印了武器行 —— {text}'
