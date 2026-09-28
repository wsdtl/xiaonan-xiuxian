"""同一只读战报内共享标量描述，不跨战报或原始可变事实共享。"""
from types import SimpleNamespace
from game.core.combat.contracts import BattleEvent
from game.core.combat.report import _event_reports
from test_combat_entry_surfaces import services


def reports(services,values):
    events=[BattleEvent(turn=0,kind='恢复后',source='甲',target='乙',text='恢复',values=value) for value in values]
    return _event_reports(SimpleNamespace(events=events),{},{},{},services.combat.report_catalog())


def test_scalar_descriptors_share_only_inside_one_report(services):
    first=reports(services,[{'状态':'回春'},{'状态':'回春'}])
    second=reports(services,[{'状态':'回春'}])
    assert first[0]['details'][0] is first[1]['details'][0]
    assert first[0]['details'][0]==second[0]['details'][0]
    assert first[0]['details'][0] is not second[0]['details'][0]


def test_descriptor_keys_keep_boolean_and_numeric_types_separate(services):
    values=reports(services,[{'判定':True},{'判定':1},{'判定':1.0},{'判定':None}])
    assert [r['details'][0]['display'] for r in values]==['是','1','1','未进行判定']
    assert values[0]['details'][0] is not values[1]['details'][0]
    assert values[1]['details'][0] is not values[2]['details'][0]


def test_nested_facts_stay_independent_of_each_other_and_input(services):
    original={'层数':[1,2]}
    output=reports(services,[{'记录':original},{'记录':original}])
    left=output[0]['details'][0]['value']
    right=output[1]['details'][0]['value']
    assert left==right==original
    assert left is not right and left is not original
    left['层数'].append(3)
    assert right==original=={'层数':[1,2]}
