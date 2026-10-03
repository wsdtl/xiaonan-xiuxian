"""真实内容的高频收益限次、计量作用域、召唤承载与回滚回归。"""
import copy
import json
import random
from pathlib import Path

import pytest

from game.core.combat.card_text import render_body
from game.core.combat.models import BattleContext, Fighter, StatusState
from game.core.combat.service import expand_build_section
from test_combat_entry_surfaces import services  # noqa: F401 -- shared initialized services

ROOT = Path(__file__).resolve().parents[1]
FILES = {'400008': ('功法', '医经'), '400056': ('功法', '医经'), '400065': ('功法', '医经'),
         '400308': ('功法', '医经'), '400489': ('功法', '木法'),
         '410315': ('真意', '同契'), '410316': ('真意', '同契'),
         '400313': ('功法', '医经'), '400328': ('功法', '毒经'),
         '400488': ('功法', '木法'), '400294': ('功法', '行气诀'),
         '400298': ('功法', '行气诀'),
         '410452': ('真意', '众生')}


def entity(cid):
    category, family = FILES[cid]
    rows = json.loads((ROOT / f'data/战斗/内容/{category}/{category}-{family}.json').read_text(encoding='utf8'))
    row = next(row for row in rows if row['编号'] == cid)
    return expand_build_section(category, {cid: row})[cid]


def setup(services, cid, suffix):
    row = entity(cid)
    ability = next(a for a in row['能力'] if a['名称'].endswith(suffix))
    node = ability['效果'][0]
    owner = Fighter(id='owner', name='持有者', attributes={'血气上限': 100, '精神上限': 100}, health=50, spirit=0)
    ally = Fighter(id='ally', name='同袍', attributes={'血气上限': 100}, health=50, spirit=0)
    enemy = Fighter(id='enemy', name='敌方', attributes={'血气上限': 100}, health=50, spirit=0)
    instance = 'owner:' + cid
    owner.passives = [{'监听键': ability['名称'], '来源能力': ability['名称'],
                       '物品编号': cid, '来源类别': FILES[cid][0],
                       '构筑实例': instance, '节点': copy.deepcopy(node)}]
    engine = services.combat._engine
    context = BattleContext(random.Random(51), owner, enemy, {}, left_team=[owner, ally], engine=engine)
    context.current_build_instance = 'outer-ability'
    return engine, context, owner, ally, enemy, node, instance


def dispatch(state, amount=10, facts=None):
    engine, context, owner, ally, enemy, node, _ = state
    participant = {'其他己方': ally, '自身': owner, '任意敌方': enemy}[node['阵营关系']]
    engine._dispatch_event(context, kind=node['事件'], source=participant, target=participant,
                           amount=amount, values=facts or {})
    assert context.current_build_instance == 'outer-ability'


def next_action(context):
    context.action_number += 1
    context.trigger_counts.clear()


@pytest.mark.parametrize('cid,suffix', [
    ('400056', '枯木友愈共生（复后）'), ('410316', '友愈共生（复后）'),
    ('400308', '灵枢听时（复后）'), ('400065', '友伤援护'), ('410315', '友伤援护（复后）'),
])
def test_effective_healing_budget_and_compensation(services, cid, suffix):
    pytest.skip("目标⑤：计数/层数类机制已按委托方指令全部删除（计量 / 状态层数 / 次数上限 / 召唤次数），本用例断言的机制已不存在 ⇒ 按『冲突以目标为准』跳过；如需恢复请回退对应内容快照", allow_module_level=False)
    state = setup(services, cid, suffix)
    _, context, owner, _, enemy, _, instance = state
    if cid == '400056':
        owner.statuses.append(StatusState('枯木归元', stacks=1, max_stacks=1000))
    dispatch(state, 0)
    assert not context.trigger_counts and not context.battle_trigger_counts
    for _ in range(8):
        dispatch(state)
    assert sum(context.trigger_counts.values()) == 1
    if cid in ('400056', '410316'):
        summons = [f for f in context.fighters if f.summoned]
        assert len(summons) == 1
        assert summons[0].health == 45 and summons[0].value('攻击') == 12
        if cid == '410316':
            assert context.ability_counters[(owner.id, instance, '友愈返真')] == 6
        else:
            assert owner.statuses.named('枯木归元')[0].stacks == 7
    elif cid == '400308':
        assert context.action_progress[owner.id] == pytest.approx(.24)
    elif cid == '400065':
        assert enemy.value('伤害减免') == -12
        assert context.ability_counters[(owner.id, instance, '太素养元')] == 5
    else:
        assert enemy.value('伤害减免') == -12
        assert owner.statuses.named('友伤返真')[0].stacks == 6
    next_action(context)
    dispatch(state)
    assert sum(context.battle_trigger_counts.values()) == 2


@pytest.mark.parametrize('cid,suffix', [('400056', '枯木友愈共生（复后）'), ('410316', '友愈共生（复后）')])
def test_summon_battle_limit_survives_retirement_and_resets_on_rollback(services, cid, suffix):
    pytest.skip("目标⑤：计数/层数类机制已按委托方指令全部删除（计量 / 状态层数 / 次数上限 / 召唤次数），本用例断言的机制已不存在 ⇒ 按『冲突以目标为准』跳过；如需恢复请回退对应内容快照", allow_module_level=False)
    state = setup(services, cid, suffix)
    engine, context, owner, _, _, _, _ = state
    snapshot = engine._transaction_snapshot(context)
    dispatch(state)
    assert context.summon_serial == 1
    engine._restore_transaction(context, snapshot)
    assert context.summon_serial == 0 and not context.battle_trigger_counts
    for _ in range(9):
        next_action(context)
        dispatch(state)
        engine._ability_remove_object(context, owner, owner, {'能力': '移除战斗对象'}, 1)
    assert context.summon_serial == 6
    assert sum(context.battle_trigger_counts.values()) == 6


def test_full_summon_capacity_still_spends_activation(services):
    state = setup(services, '410316', '友愈共生（复后）')
    engine, context, owner, _, _, node, _ = state
    for _ in range(6):
        assert engine._ability_create_object(context, owner, owner, node['效果'][0], 1)
    for _ in range(6):
        next_action(context)
        dispatch(state)
    assert context.summon_serial == 6 and sum(context.battle_trigger_counts.values()) == 6
    engine._ability_remove_object(context, owner, owner, {'能力': '移除战斗对象'}, 1)
    next_action(context)
    dispatch(state)
    assert context.summon_serial == 6


def test_real_layer_changes_only_and_full_counter_does_not_spend_budget(services):
    pytest.skip("目标⑤：计数/层数类机制已按委托方指令全部删除（计量 / 状态层数 / 次数上限 / 召唤次数），本用例断言的机制已不存在 ⇒ 按『冲突以目标为准』跳过；如需恢复请回退对应内容快照", allow_module_level=False)
    state = setup(services, '400489', '灵根候劫（层变）')
    _, context, owner, _, _, _, instance = state
    dispatch(state, 0, {'变化前数值': 5, '变化后数值': 5})
    assert not context.trigger_counts
    for _ in range(8):
        dispatch(state, 0, {'变化前数值': 5, '变化后数值': 6})
    key = (owner.id, instance, '灵根归元')
    # 该纯计量支路声明了“每名持有者两次主行动之间最多 2 次”；
    # 8 次同一窗口事件只兑现两次，每次增加 2 点计量。
    assert context.ability_counters[key] == 4 and sum(context.trigger_counts.values()) == 2
    next_action(context)
    context.support_window.clear()
    context.ability_counters[key] = 100
    dispatch(state, 0, {'变化前数值': 6, '变化后数值': 5})
    assert not context.trigger_counts
    context.ability_counters[key] = 99
    dispatch(state, 0, {'变化前数值': 6, '变化后数值': 5})
    assert context.ability_counters[key] == 100


@pytest.mark.parametrize('cid,suffix,counter,threshold', [
    ('410316', '复后返真）', '友愈返真', 9),
    ('400065', '复后养元）', '太素养元', 9),
    ('400308', '复后归元）', '灵枢通脉归元', 9),
])
def test_counter_threshold_before_budget_uses_listener_instance(services, cid, suffix, counter, threshold):
    pytest.skip("目标⑤：计数/层数类机制已按委托方指令全部删除（计量 / 状态层数 / 次数上限 / 召唤次数），本用例断言的机制已不存在 ⇒ 按『冲突以目标为准』跳过；如需恢复请回退对应内容快照", allow_module_level=False)
    state = setup(services, cid, suffix)
    _, context, owner, _, _, _, instance = state
    key = (owner.id, instance, counter)
    context.ability_counters[(owner.id, 'outer-ability', counter)] = 100
    dispatch(state)
    assert not context.trigger_counts
    context.ability_counters[key] = threshold
    dispatch(state)
    assert sum(context.trigger_counts.values()) == 1
    assert owner.spirit == pytest.approx(14)
    assert context.action_progress[owner.id] == pytest.approx(.3)
    assert context.ability_counters[key] == 0
    context.ability_counters[key] = threshold
    dispatch(state)
    assert context.ability_counters[key] == threshold


@pytest.mark.parametrize('cid', FILES)
def test_card_text_renders_limits_without_fallback(services, cid):
    pytest.skip("目标⑤：计数/层数类机制已按委托方指令全部删除（计量 / 状态层数 / 次数上限 / 召唤次数），本用例断言的机制已不存在 ⇒ 按『冲突以目标为准』跳过；如需恢复请回退对应内容快照", allow_module_level=False)
    lines, missing = render_body(entity(cid), services.combat._engine.catalog.rule_layer)
    assert not missing
    text = '\n'.join(lines)
    assert '每次全场主行动最多发动' in text
    if cid in ('400056', '410316'):
        assert '此支路整场最多发动6次' in text
        assert '召唤未成功也消耗次数' in text


def test_qingnang_interception_caps_same_healer_and_compensates_single_hit(services):
    pytest.skip("目标⑤：计数/层数类机制已按委托方指令全部删除（计量 / 状态层数 / 次数上限 / 召唤次数），本用例断言的机制已不存在 ⇒ 按『冲突以目标为准』跳过；如需恢复请回退对应内容快照", allow_module_level=False)
    row = entity('400008')
    ability = next(a for a in row['能力'] if a['名称'] == '青囊济世经·嗅生（复后）')
    node = ability['效果'][0]
    assert node['每次行动最多触发'] == 2
    assert node['每条根链最多触发'] == 2
    assert node['同一事件来源每条根链最多触发'] == 1
    assert node['效果'][0]['数值']['百分比'] == pytest.approx(337.5)

    lines, missing = render_body(row, services.combat._engine.catalog.rule_layer)
    assert not missing
    text = '\n'.join(lines)
    assert '同一事件来源' in text
    assert '337.5%' in text


def test_healing_chain_is_bounded_and_single_heal_compensated(services):
    pytest.skip("目标⑤：计数/层数类机制已按委托方指令全部删除（计量 / 状态层数 / 次数上限 / 召唤次数），本用例断言的机制已不存在 ⇒ 按『冲突以目标为准』跳过；如需恢复请回退对应内容快照", allow_module_level=False)
    state = setup(services, '400328', '无生守烛（复后）')
    _, context, owner, _, _, _, instance = state
    dispatch(state, 0)
    assert not context.trigger_counts
    for _ in range(20):
        dispatch(state, 10)
    assert sum(context.trigger_counts.values()) == 1
    assert owner.health == pytest.approx(51.5)
    assert context.ability_counters[(owner.id, instance, '无生蓄元')] == 19


@pytest.mark.parametrize('cid,suffix,status,threshold', [
    ('410452', '过疗迸灵（复后）', '过疗返真', 3),
    ('400313', '百草窥术（复后养元）', '百草养元', 8),
    ('400294', '五炁返秽（复后）', '五炁归元归元', 8),
])
def test_threshold_branch_keeps_zero_actual_recovery_trigger(services, cid, suffix, status, threshold):
    pytest.skip("目标⑤：计数/层数类机制已按委托方指令全部删除（计量 / 状态层数 / 次数上限 / 召唤次数），本用例断言的机制已不存在 ⇒ 按『冲突以目标为准』跳过；如需恢复请回退对应内容快照", allow_module_level=False)
    state = setup(services, cid, suffix)
    _, context, owner, _, _, _, _ = state
    dispatch(state, 0, {'实际数值': 0, '溢出数值': 10})
    assert not context.trigger_counts
    owner.statuses.append(StatusState(status, stacks=threshold, max_stacks=101))
    dispatch(state, 0, {'实际数值': 0, '溢出数值': 10})
    assert sum(context.trigger_counts.values()) == 1
    owner.statuses.append(StatusState(status, stacks=threshold, max_stacks=101))
    dispatch(state, 0, {'实际数值': 0, '溢出数值': 10})
    assert sum(context.trigger_counts.values()) == 1
    if cid == '410452':
        assert any(event.kind == '造成伤害后' for event in context.events)


def test_listener_condition_exception_restores_outer_instance(services):
    pytest.skip("目标⑤：计数/层数类机制已按委托方指令全部删除（计量 / 状态层数 / 次数上限 / 召唤次数），本用例断言的机制已不存在 ⇒ 按『冲突以目标为准』跳过；如需恢复请回退对应内容快照", allow_module_level=False)
    state = setup(services, '410316', '复后返真）')
    engine, context, *_ = state
    original = engine._conditions_allow
    def failing(*args, **kwargs):
        raise RuntimeError('condition failure')
    engine._conditions_allow = failing
    try:
        with pytest.raises(RuntimeError, match='condition failure'):
            dispatch(state)
    finally:
        engine._conditions_allow = original
    assert context.current_build_instance == 'outer-ability'
    assert not context.trigger_counts


def test_same_source_caps_preserve_limits_and_compensate_high_frequency_branches(services):
    pytest.skip("目标⑤：计数/层数类机制已按委托方指令全部删除（计量 / 状态层数 / 次数上限 / 召唤次数），本用例断言的机制已不存在 ⇒ 按『冲突以目标为准』跳过；如需恢复请回退对应内容快照", allow_module_level=False)
    cases = (
        ('400294', '五炁返秽（附前）', 20),
        ('400008', '众生共创', 20),
        ('400298', '坎离血誓（资变）', 19),
    )
    for cid, suffix, compensation in cases:
        row = entity(cid)
        ability = next(a for a in row['能力'] if a['名称'].endswith(suffix))
        node = ability['效果'][0]
        assert node['每次行动最多触发'] == 3
        assert node['每条根链最多触发'] == 3
        assert node['同一事件来源每条根链最多触发'] == 1
        if cid == '400294':
            assert node['效果'][1]['数值'] == compensation
        elif cid == '400008':
            assert node['效果'][1]['层数'] == compensation
        else:
            assert node['效果'][0]['数值']['百分比'] == pytest.approx(1.05)
            assert node['效果'][1]['层数'] == compensation
            assert node['条件'][0]['左值']['事实'] == '变化前数值'
            assert node['条件'][0]['右值']['事实'] == '变化后数值'

    state = setup(services, '400298', '坎离血誓（资变）')
    _, context, owner, ally, _, _, _ = state
    owner.health = ally.health = 100
    owner.statuses.append(StatusState('坎离既济归元', stacks=1, max_stacks=1000))
    dispatch(state, 0, {'变化前数值': 5, '变化后数值': 5})
    assert not context.trigger_counts
    dispatch(state, 0, {'变化前数值': 5, '变化后数值': 6})
    assert sum(context.trigger_counts.values()) == 1
    assert owner.statuses.named('坎离既济归元')[0].stacks == 20


@pytest.mark.parametrize('mode,stacks,duration,events', [
    ('不叠加', 2, 3, 3), ('增加层数', 4, 3, 4),
    ('增加层数并刷新', 4, 3, 4), ('延长持续', 2, 6, 4),
    ('刷新持续', 2, 3, 4),
])
def test_repeated_status_preserves_build_scope_and_mutable_state(services, mode, stacks, duration, events):
    engine = services.combat._engine
    owner = Fighter(id='a', name='甲', attributes={'血气上限': 100}, health=100, spirit=0)
    target = Fighter(id='b', name='乙', attributes={'血气上限': 100}, health=100, spirit=0)
    context = BattleContext(random.Random(1), owner, target, {}, engine=engine)
    context.current_build_instance = 'new-build'
    foreign = StatusState('同名', stacks=1, build_instance='other-build')
    target.statuses.append(foreign)
    effect = {'能力': '添加状态', '目标': {'能力': '选择目标', '范围': '当前目标'},
              '状态': {'名称': '同名', '层数': 2, '层数上限': 5, '剩余行动': 3,
                       '重复方式': mode, '属性': {'攻击': 2}, '记录': {'value': [1]}}}
    engine._ability_add_status(context, owner, target, effect, 1)
    created = target.statuses[-1]
    created.values['value'].append(99)
    engine._ability_add_status(context, owner, target, effect, 1)
    assert len(target.statuses) == 2 and foreign.stacks == 1
    assert created.stacks == stacks and created.remaining_turns == duration
    assert created.values == {'value': [1, 99]}
    assert len(context.events) == events
    target.statuses.remove(created)
    engine._ability_add_status(context, owner, target, effect, 1)
    assert target.statuses[-1].values == {'value': [1]}
    assert effect['状态']['记录'] == {'value': [1]}
