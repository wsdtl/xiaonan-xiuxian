"""状态索引和事务快照的动态变更回归。"""
import copy
import math
import random
from dataclasses import asdict
from types import SimpleNamespace
from collections import UserDict

import pytest

from game.core.combat.mechanics import AbilityRuntime, _CandidateList
from game.core.combat.models import BattleContext, EventFrame, Fighter, Skill, StatusList, StatusState


def fighter(key='left'):
    return Fighter(id=key, name=key, attributes={'攻击': 10.0}, health=100, spirit=100)


def test_status_index_tracks_direct_mutation_and_shared_status():
    status = StatusState('甲', modifiers={'攻击': 2.0}, stacks=2)
    left, right = fighter(), fighter('right')
    left.statuses.append(status)
    right.statuses.append(status)
    assert left.value('攻击') == right.value('攻击') == 14
    status.modifiers.update({'攻击': 3.0, '防御': 4.0})
    assert left.value('防御') == right.value('防御') == 8
    status.stacks = 3
    assert left.value('攻击') == right.value('攻击') == 19
    status.name = '乙'
    assert not left.statuses.named('甲')
    assert list(right.statuses.named('乙')) == [status]
    status.rules['test'] = {'拦截点': '被选为目标'}
    assert list(left.statuses.with_rules()) == [status]
    status.rules.clear()
    assert not left.statuses.with_rules()
    status.modifiers = {'攻击': -1.0}
    assert left.value('攻击') == right.value('攻击') == 7


def test_appended_status_still_invalidates_both_owners_on_mutation():
    left, right = fighter(), fighter('right')
    existing = StatusState('甲', modifiers={'攻击': 0.1})
    left.statuses.append(existing)
    assert left.value('攻击') == 10.1
    shared = StatusState('甲', modifiers={'攻击': 0.2}, stacks=2)
    left.statuses.append(shared)
    right.statuses.append(shared)
    assert left.value('攻击') == 10.1 + 0.4
    assert list(left.statuses.named('甲')) == [existing, shared]
    assert right.value('攻击') == 10.4
    shared.name = '乙'
    shared.modifiers['防御'] = 3
    shared.rules['new'] = {'拦截点': '被选为目标'}
    assert list(left.statuses.named('甲')) == [existing]
    assert list(right.statuses.named('乙')) == [shared]
    assert left.value('防御') == right.value('防御') == 6
    assert list(left.statuses.with_rules()) == [shared]
    left.statuses.remove(shared)
    shared.modifiers['防御'] = 4
    assert left.value('防御') == 0 and right.value('防御') == 8


@pytest.mark.parametrize('operation', [
    lambda states, value: states.append(value),
    lambda states, value: states.extend([value]),
    lambda states, value: states.insert(0, value),
    lambda states, value: states.__setitem__(slice(None), [value]),
    lambda states, value: states.__iadd__([value]),
])
def test_status_list_edits_preserve_scan_order(operation):
    owner = fighter()
    owner.statuses = [StatusState('甲', modifiers={'攻击': 0.1})]
    owner.value('攻击')
    operation(owner.statuses, StatusState('乙', modifiers={'攻击': 0.2}, stacks=3))
    expected = 10.0
    for status in owner.statuses:
        expected += status.modifiers.get('攻击', 0) * max(1, status.stacks)
    assert owner.value('攻击') == expected
    owner.statuses.reverse()
    expected = 10.0
    for status in owner.statuses:
        expected += status.modifiers.get('攻击', 0) * max(1, status.stacks)
    assert owner.value('攻击') == expected
    owner.statuses.clear()
    assert owner.value('攻击') == 10


def test_snapshot_reuse_delete_and_deepcopy_are_isolated():
    original = Skill('a', '甲')
    original.extra = {'nested': [1]}
    snapshot = original.snapshot_state()
    assert original.snapshot_state() is snapshot
    original.uses = 1
    assert original.snapshot_state() is not snapshot
    del original.extra
    assert 'extra' not in original.snapshot_state()[1]
    restored = AbilityRuntime._restore_instances([snapshot])[0]
    assert restored.uses == 0 and restored.extra == {'nested': [1]}
    copied = copy.deepcopy(restored)
    copied.extra['nested'].append(2)
    assert restored.extra['nested'] == [1]
    restored.uses = 5
    assert AbilityRuntime._restore_instances([snapshot])[0].uses == 0


def test_deepcopied_status_index_does_not_inherit_subscribers():
    owner = fighter()
    owner.statuses = [StatusState('甲', modifiers={'攻击': 2.0})]
    owner.value('攻击')
    owner.statuses[0].snapshot_state()
    cloned = copy.deepcopy(owner)
    assert isinstance(cloned.statuses, StatusList)
    assert cloned.value('攻击') == 12
    cloned.statuses[0].modifiers['攻击'] = 8.0
    assert cloned.value('攻击') == 18
    assert owner.value('攻击') == 12
    assert asdict(owner.statuses[0])['modifiers'] == {'攻击': 2.0}


def test_transaction_restores_counts_rng_frames_and_reusable_snapshot():
    owner, target = fighter(), fighter('right')
    owner.extension_counter = 17
    owner.skills = [Skill('skill', '甲')]
    context = BattleContext(random.Random(71), owner, target, {})
    key = ('left', 'listener')
    context.trigger_counts[key] = 1
    context.battle_trigger_counts[key] = 2
    snapshot = AbilityRuntime._transaction_snapshot(context)
    random_value = context.rng.random()
    context.trigger_counts[key] = 5
    context.battle_trigger_counts[key] = 7
    owner.skills[0].uses = 6
    owner.extension_counter = 29
    AbilityRuntime._restore_transaction(context, snapshot)
    assert context.trigger_counts[key] == 1

    assert context.battle_trigger_counts[key] == 2
    assert context.rng.random() == random_value
    assert owner.skills[0].uses == 0
    assert owner.extension_counter == 17
    assert copy.deepcopy(owner).extension_counter == 17
    context.trigger_counts[key] = 99
    AbilityRuntime._restore_transaction(context, snapshot)
    assert context.trigger_counts[key] == 1


def test_transaction_restores_effect_history_window():
    owner, target = fighter(), fighter('right')
    context = BattleContext(random.Random(73), owner, target, {})
    context.effect_history.extend([{'成功': True, '节点': {'序号': 1}}, {'成功': True, '节点': {'序号': 2}}])
    snapshot = AbilityRuntime._transaction_snapshot(context)
    context.effect_history[:] = [{'成功': True, '节点': {'序号': 99}}]
    AbilityRuntime._restore_transaction(context, snapshot)
    assert [item['节点']['序号'] for item in context.effect_history] == [1, 2]


@pytest.mark.parametrize('initial,shadow,expected', [
    (100, None, 100),
    ([100], None, 31),
    ((100,), None, (100,)),
    (100, {'health': 17}, 17),
    (100, {'health': {'ignored': 1}}, 100),
])
def test_fighter_snapshot_preserves_scalar_filter_and_extension_shadowing(initial, shadow, expected):
    owner=fighter()
    owner.health=initial
    owner.extension_counter=17
    owner.extension_mutable={'unchanged_contract': 1}
    if shadow:
        owner.__dict__.update(shadow)
    snapshot=AbilityRuntime._snapshot_fighter(owner)
    owner.health=31
    owner.extension_counter=99
    owner.extension_mutable={'after': 2}
    owner.attributes['攻击']=35
    AbilityRuntime._restore_fighter(owner,snapshot)
    assert owner.health==expected
    assert owner.extension_counter==17
    assert owner.extension_mutable=={'after': 2}
    assert owner.attributes=={'攻击': 10.0}
    owner.extension_counter=44
    AbilityRuntime._restore_fighter(owner,snapshot)
    assert owner.extension_counter==17


@pytest.mark.parametrize('initial', [{}, 17])
def test_fighter_snapshot_keeps_rule_cache_filtering(initial):
    owner=fighter()
    owner.rules_cache=initial
    snapshot=AbilityRuntime._snapshot_fighter(owner)
    replacement={'fresh': []}
    owner.rules_cache=replacement
    AbilityRuntime._restore_fighter(owner,snapshot)
    assert owner.rules_cache is (replacement if isinstance(initial,dict) else initial)


def test_fighter_subclass_keeps_snapshot_attribute_read_order():
    class ExtendedFighter(Fighter):
        def __getattribute__(self,name):
            if name in Fighter.__slots__:
                object.__getattribute__(self,'attribute_reads').append(name)
            return super().__getattribute__(name)
    owner=ExtendedFighter(id='left',name='left',attributes={},health=100,spirit=100)
    owner.attribute_reads=[]
    AbilityRuntime._snapshot_fighter(owner)
    assert owner.attribute_reads[:len(Fighter.__slots__)]==list(Fighter.__slots__)


@pytest.mark.parametrize('kind', ['恢复后', '状态层数变化后', '行动条变化后'])
def test_zero_change_report_omission_preserves_listener_and_rng(kind):
    class Runtime(AbilityRuntime):
        _event_names = frozenset({kind})
        recorded_facts = None

        def _listeners_for(self, context, *args):
            return list(enumerate(context.listener_index[kind]))

        def _listener_relation_matches(self, *args):
            return True

        def _run_effects(self, context, owner, target, *args, **kwargs):
            target.health += context.rng.random()
            return True

    def run(compressed, amount):
        owner, target = fighter(), fighter('right')
        context = BattleContext(random.Random(63), owner, target, {})
        context.listener_index_dirty = False
        activation = ('left', 'zero-change-hook')
        entry = (0, owner, 'hook', None, '测试', '', {}, {}, (), 0, 0, (), True, activation)
        context.listener_index[kind] = (entry,)
        if compressed:
            context.event_capture_filter = frozenset()
            context.event_capture_zero_change_kinds = frozenset({kind})
        Runtime()._dispatch_event(
            context, kind=kind, source=owner, target=target, amount=amount,
            values={'变化前数值': 10, '变化后数值': 10 + amount},
        )
        return context

    full, compressed = run(False, 0), run(True, 0)
    assert len(full.events) == 1 and not compressed.events
    assert full.event_count == compressed.event_count == 1
    assert full.right.health == compressed.right.health > 100
    assert full.trigger_counts == compressed.trigger_counts
    assert full.battle_trigger_counts == compressed.battle_trigger_counts
    assert full.rng.getstate() == compressed.rng.getstate()
    assert len(run(True, 1).events) == 1


@pytest.mark.parametrize("size", [1, 2, 8, 9])
def test_exhausted_candidates_return_after_rollback_and_new_action(size):
    context = BattleContext(random.Random(1), fighter(), fighter('right'), {})
    key = ('left', 'listener')
    entry = (None,) * 9 + (1, 0, (), True, key)
    random_entry = (None,) * 9 + (1, 0, (), False, key)
    pairs = _CandidateList([(index, entry) for index in range(size)] + [(size, random_entry)], filtered_version=0)
    context.trigger_counts[key] = 1
    assert [p for p, _ in pairs.available(context)] == [size]
    context.trigger_counts = {}
    assert [p for p, _ in pairs.available(context)] == list(range(size + 1))
    context.trigger_counts[key] = 1
    context.listener_budget_version += 1
    assert [p for p, _ in pairs.available(context)] == [size]
    context.action_number += 1
    context.trigger_counts.clear()
    assert [p for p, _ in pairs.available(context)] == list(range(size + 1))


def test_candidate_availability_cache_invalidates_only_when_trigger_budgets_change():
    class CountingDict(dict):
        reads = 0

        def get(self, *args, **kwargs):
            self.reads += 1
            return super().get(*args, **kwargs)

    context = BattleContext(random.Random(1), fighter(), fighter('right'), {})
    context.trigger_counts = CountingDict()
    context.battle_trigger_counts = CountingDict()
    context.chain_counts = CountingDict()
    key = ('left', 'listener')
    entry = (None,) * 9 + (1, 0, (), True, key)
    pairs = _CandidateList([(index, entry) for index in range(10)], filtered_version=0)

    assert len(pairs.available(context)) == 10
    reads = context.trigger_counts.reads + context.battle_trigger_counts.reads + context.chain_counts.reads
    assert len(pairs.available(context)) == 10
    assert context.trigger_counts.reads + context.battle_trigger_counts.reads + context.chain_counts.reads == reads
    context.trigger_counts[key] = 1
    context.listener_budget_version += 1
    assert pairs.available(context) == []
    reads = context.trigger_counts.reads + context.battle_trigger_counts.reads + context.chain_counts.reads
    assert pairs.available(context) == []
    assert context.trigger_counts.reads + context.battle_trigger_counts.reads + context.chain_counts.reads == reads


def test_long_candidate_budget_recovers_at_next_root_with_same_count_dict():
    context = BattleContext(random.Random(1), fighter(), fighter('right'), {})
    entries = [
        (None,) * 9 + (0, 0, (), True, ('left', str(index)), 2, 1, '', 0)
        for index in range(10)
    ]
    pairs = _CandidateList(list(enumerate(entries)), filtered_version=0)
    assert len(pairs.available(context)) == 10
    for entry in entries[:5]:
        context.chain_counts[entry[13]] = 1
    context.listener_budget_version += 1
    assert [position for position, _ in pairs.available(context)] == list(range(5, 10))
    for entry in entries[5:]:
        context.chain_counts[entry[13]] = 1
    context.listener_budget_version += 1
    assert pairs.available(context) == []
    context.chain_serial += 1
    context.chain_counts.clear()
    assert len(pairs.available(context)) == 10


def test_named_status_selection_preserves_filters_order_and_mutation():
    owner = fighter()
    context = BattleContext(random.Random(1), owner, fighter('right'), {})
    context.current_build_instance = 'a'
    first = StatusState('甲', category='正面', tags=('木',), stacks=1, remaining_turns=3, build_instance='a')
    foreign = StatusState('甲', category='正面', tags=('木',), stacks=5, remaining_turns=1, build_instance='b')
    shared = StatusState('甲', category='负面', tags=('木', '毒'), stacks=4, remaining_turns=2)
    last = StatusState('甲', category='正面', tags=('木',), stacks=2, remaining_turns=5, build_instance='a')
    owner.statuses.extend([first, StatusState('乙'), foreign, shared, last])
    runtime = AbilityRuntime()
    selectors = [
        ({'名称': '甲'}, [first]),
        ({'名称': '甲', '选择全部': True}, [first, shared, last]),
        ({'名称': '甲', '分类': '正面', '标签': ['木'], '选择全部': True}, [first, last]),
        ({'名称': '甲', '分类': '正面', '允许跨构筑': True, '选择全部': True, '排序': '层数从高到低'}, [foreign, last, first]),
        ({'名称': '甲', '数量': 2, '排序': '剩余行动从少到多'}, [shared, first]),
        ({'名称': '甲', '标签': ['毒'], '选择全部': True}, [shared]),
        ({'名称': '不存在'}, []),
    ]
    for warm in (False, True):
        if warm:
            owner.statuses.build_indexes()
        for selector, expected in selectors:
            actual = runtime._matching_statuses(context, owner, selector)
            assert len(actual) == len(expected)
            assert all(a is b for a, b in zip(actual, expected))
        assert (owner.statuses.modifier_index is not None) == warm
    first.name = '乙'
    assert runtime._matching_statuses(context, owner, {'名称': '甲'}) == [shared]
    owner.statuses.build_indexes()
    owner.statuses.remove(shared)
    assert runtime._matching_statuses(context, owner, {'名称': '甲'}) == [last]


def test_status_template_isolated_from_live_mutation_and_event_rewrite():
    class Runtime(AbilityRuntime):
        def _select_targets(self, context, source, target, value):
            return [target]

        def _dispatch_event(self, context, *, kind, source, target, values, tags=(), **kwargs):
            if kind == '添加状态前' and context.saved_results.get('rewrite'):
                values['状态定义']['剩余行动'] = 7
            return EventFrame(kind, source, target, dict(values), set(tags))

        def _status_with_rules(self, definition, path):
            return StatusState.from_dict(definition)

        def _resolve_status_reactions(self, *args):
            return None

    runtime = Runtime()
    owner, target = fighter(), fighter('right')
    context = BattleContext(random.Random(4), owner, target, {})
    target.rules_cache_version = 0
    effect = {'状态': {'名称': '甲', '属性': {'攻击': 2}, '剩余行动': 3, '记录': {'nested': [1]}}}
    runtime._ability_add_status(context, owner, target, effect, 1)
    target.statuses[0].values['nested'].append(9)
    target.statuses[0].modifiers['攻击'] = 99
    target.statuses.clear()
    runtime._ability_add_status(context, owner, target, effect, 1)
    assert target.statuses[0].values == {'nested': [1]}
    assert target.statuses[0].modifiers == {'攻击': 2}
    target.statuses.clear()
    context.saved_results['rewrite'] = True
    runtime._ability_add_status(context, owner, target, effect, 1)
    assert target.statuses[0].remaining_turns == 7


@pytest.mark.parametrize('value', [-20, -0.0, 0.0, 7.5, 30, float('nan'), float('inf')])
def test_compiled_numeric_bounds_match_interpreter(value):
    class Runtime(AbilityRuntime):
        def _select_targets(self, context, source, target, selector):
            return [target]

        def _container_rules(self, *args):
            return {}

    runtime = Runtime()
    owner, target = fighter(), fighter('right')
    context = BattleContext(random.Random(1), owner, target, {})
    node = {'来源': '事件事实', '事实': '值', '百分比': 125, '最低值': -0.0, '最高值': 12}
    actual = runtime._compile_read_value(node)(context, owner, target, node, 0, {'值': value})
    expected = runtime._value_read(context, owner, target, node, 0, {'值': value})
    assert actual == expected or math.isnan(actual) and math.isnan(expected)
    assert math.copysign(1, actual) == math.copysign(1, expected)


@pytest.mark.parametrize('executor', ['数值条件', '组合条件'])
def test_custom_condition_handler_is_not_constant_folded(executor):
    runtime = AbilityRuntime()
    custom = lambda *args: False
    runtime._condition_handlers = {executor: custom}
    definition = {'左值': 1, '右值': 1, '比较': '等于', '条件': []}
    raw, handler, kind = runtime._compile_condition_plan_item(definition, executor)
    assert raw is definition and handler is custom and kind == executor


@pytest.mark.parametrize('redirect_back', [False, True])
def test_dispatch_target_rewrites_resume_only_after_last_position(redirect_back):
    owner, target = fighter(), fighter('right')
    context = BattleContext(random.Random(1), owner, target, {})
    seen = []

    def entry(position, name):
        return (position, owner, name, name, name, 'build', {}, {}, (),
                0, 0, (), True, (owner.id, name), 2, 1, '', 0)

    entries = [entry(i, name) for i, name in enumerate(('first', 'skipped', 'back', 'last'))]

    class Runtime(AbilityRuntime):
        _event_names = frozenset({'恢复后'})
        recorded_facts = None

        def _listeners_for(self, context, kind, frame, parties=None):
            indexes = (0, 1, 3) if frame.target is target else ((0, 2) if redirect_back else ())
            return _CandidateList(((i, entries[i]) for i in indexes),
                                  filtered_version=context.listener_table_version)

        def _run_effects(self, context, source, selected, *args, **kwargs):
            seen.append(context.current_ability)
            frame = context.event_stack[-1]
            if context.current_ability == 'first':
                frame.target = owner
            elif context.current_ability == 'back':
                frame.target = target

    runtime = Runtime()
    context.listener_index_dirty = False
    context.listener_index = {'恢复后': tuple(entries)}
    frame = runtime._dispatch_event(context, kind='恢复后', source=owner, target=target)
    assert seen == (['first', 'back', 'last'] if redirect_back else ['first'])
    assert frame.target is (target if redirect_back else owner)
    assert not context.event_stack and context.event_depth == 0
    assert sum(context.battle_trigger_counts.values()) == len(seen)


def test_element_composition_cache_shares_values_and_observes_changes():
    runtime = AbilityRuntime()
    runtime.catalog = SimpleNamespace(five_elements={'倍率': {'相克': 1.15, '团队相生': 1.08}})
    runtime._element_overcoming = {'木': '土', '金': '木'}
    owner, target = fighter(), fighter('right')
    owner.five_elements = {'木': 100}
    target.five_elements = {'土': 100}
    context = BattleContext(random.Random(1), owner, target, {})
    for _ in range(100):
        result = runtime._element_multiplier(context, owner, target, {'属性构成': {'木': 100}})
        assert result == pytest.approx(1.4 * 1.15)
    assert len(context.element_composition_cache) == 1
    assert context.element_composition_cache[(('木', 100),)][0] == {'木': 100.0}

    effect = {'属性构成': {'木': 100}}
    owner.team_synergy['木'] = 1
    assert runtime._element_multiplier(context, owner, target, effect) == pytest.approx(result * 1.08)
    assert runtime._element_multiplier(context, owner, target, effect) == pytest.approx(result)
    effect['属性构成'].clear()
    effect['属性构成']['金'] = 100
    assert runtime._element_multiplier(context, owner, target, effect) == pytest.approx(.9)
    assert len(context.element_composition_cache) == 2
    effect['属性构成'] = UserDict({'木': '100'})
    assert runtime._element_multiplier(context, owner, target, effect) == pytest.approx(result)
    assert len(context.element_composition_cache) == 2
