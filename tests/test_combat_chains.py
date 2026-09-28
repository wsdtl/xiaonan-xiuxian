"""根链预算、三速资格、链尾兑现和动态规则身份的行为回归。"""
import random
import pytest
from game.core.combat.models import BattleContext, EventFrame, Fighter
from game.core.combat.mechanics import _ListenerSink
from game.core.combat.foundation import EVENT_LISTENER_SORT_ORDER
from test_combat_entry_surfaces import services


def counter(name, amount=1):
    return {'能力':'修改构筑计量','目标':{'能力':'选择目标','范围':'自身'},
            '计量':name,'方式':'增加','数值':amount,'最高值':100}


def listener(event='恢复后', **fields):
    return {'能力':'监听事件','事件':event,'观察角色':'来源','阵营关系':'自身',
            '效果':[counter('reward')], **fields}


def setup(services, nodes):
    owner=Fighter(id='L', name='甲', attributes={'血气上限':100,'精神上限':100},health=50,spirit=0)
    enemy=Fighter(id='R', name='乙', attributes={'血气上限':100},health=100,spirit=0)
    owner.passives=[{'监听键':str(i),'来源能力':str(i),'构筑实例':'build','物品编号':'test',
                     '能力序号':i,'节点':node} for i,node in enumerate(nodes)]
    engine=services.combat._engine
    context=BattleContext(random.Random(51),owner,enemy,{},engine=engine)
    return engine,context,owner,enemy


def emit(state, kind='恢复后', amount=10):
    engine,context,owner,_=state
    return engine._dispatch_event(context,kind=kind,source=owner,target=owner,amount=amount)


def emit_from(state, event_source, amount=10):
    engine, context, owner, _ = state
    return engine._dispatch_event(context, kind='恢复后', source=event_source, target=owner, amount=amount)


def value(state,name='reward'):
    return state[1].ability_counters.get(('L','build',name),0)


def test_rebuild_reuses_unchanged_routes_without_reusing_exhausted_budget(services):
    state=setup(services,[listener()])
    engine,ctx,owner,_=state
    engine._compiled_listeners(ctx)
    snapshot=engine._transaction_snapshot(ctx)
    emit(state)
    previous=ctx.listener_index
    bucket=ctx.listener_buckets['恢复后']
    version=ctx.listener_table_version
    engine._restore_transaction(ctx,snapshot)
    assert ctx.listener_index_dirty and ctx.listener_table_version > version
    assert ctx.listener_index is previous
    emit(state)
    assert value(state)==1
    assert ctx.event_count==1
    assert not ctx.listener_index_dirty
    assert ctx.listener_buckets['恢复后'] is bucket


def test_rebuild_recomputes_routes_after_membership_and_side_change(services):
    state=setup(services,[listener(阵营关系='任意己方')])
    engine,ctx,owner,enemy=state
    emit_from(state,enemy)
    assert value(state)==0
    ctx.right_team.remove(enemy)
    ctx.left_team.append(enemy)
    enemy.side=owner.side
    ctx.rebuild_indexes()
    emit_from(state,enemy)
    assert value(state)==1
    ctx.left_team.remove(enemy)
    ctx.right_team.append(enemy)
    enemy.side=1
    ctx.rebuild_indexes()
    emit_from(state,enemy)
    assert value(state)==1


def test_summon_preserves_listener_order_and_lazily_refreshes_candidates(services):
    state=setup(services,[listener(阵营关系='任意己方')])
    engine,ctx,owner,enemy=state
    enemy.passives=list(owner.passives)
    frame=EventFrame('恢复后',enemy,owner,{'行动者':enemy.id})
    old_pairs=engine._listeners_for(ctx,'恢复后',frame)
    old_entries=ctx.listener_index['恢复后']
    old_bucket=ctx.listener_buckets['恢复后']
    old_version=old_pairs.filtered_version
    ctx.add_fighter(Fighter(id='summon',name='援手',attributes={},health=50,spirit=0,side=0))
    engine._compiled_listeners(ctx)
    assert all(a is b for a,b in zip(old_entries,ctx.listener_index['恢复后']))
    assert ctx.listener_buckets['恢复后'] is old_bucket
    assert old_pairs.filtered_version==old_version
    new_pairs=engine._listeners_for(ctx,'恢复后',frame)
    assert new_pairs is not old_pairs
    assert [entry[1].id for _,entry in new_pairs]==[enemy.id]
    assert new_pairs.filtered_version==ctx.listener_table_version
    assert old_pairs.filtered_version==old_version


def test_summon_route_refresh_preserves_exhaustion_and_next_root_restores_it(services):
    state=setup(services,[listener() for _ in range(10)])
    engine,ctx,owner,_=state
    frame=EventFrame('恢复后',owner,owner,{'行动者':owner.id})
    with engine.root_chain(ctx):
        emit(state)
        old_pairs=engine._listeners_for(ctx,'恢复后',frame)
        assert old_pairs.available(ctx)==[]
        ctx.add_fighter(Fighter(id='summon',name='援手',attributes={},health=50,spirit=0,side=0))
        new_pairs=engine._listeners_for(ctx,'恢复后',frame)
        assert new_pairs is not old_pairs
        assert new_pairs.available(ctx)==[]
        emit(state)
        assert value(state)==10
    emit(state)
    assert value(state)==20


def test_stable_listener_order_keeps_external_owners_after_participants(services):
    engine,ctx,owner,enemy=setup(services,[])
    external=Fighter(id='field',name='战场',attributes={},health=1,spirit=0)
    for positions,fallback in ((ctx.fighter_order,None),(ctx.listener_fighter_order,(2,0))):
        sink=_ListenerSink(engine,tuple(EVENT_LISTENER_SORT_ORDER),positions,
                           participant_order_fallback=fallback)
        for actor in (external,enemy,owner):
            sink.add(actor,'same',listener(),item_id='same')
        ordered=sorted(sink.grouped['恢复后'],key=lambda entry:entry[0])
        assert [entry[1].id for entry in ordered]==[owner.id,enemy.id,external.id]


def test_one_root_covers_multiple_events_and_multihit_override(services):
    state=setup(services,[listener(),listener(每条根链最多触发=3,效果=[counter('multi')])])
    engine,ctx,*_=state
    with engine.root_chain(ctx):
        for _ in range(10): emit(state)
        assert value(state)==1 and value(state,'multi')==3
        with engine.root_chain(ctx): emit(state)
        assert ctx.chain_serial==1
    emit(state)
    assert ctx.chain_serial==2 and value(state)==2 and value(state,'multi')==4


def test_speed_three_blocks_two_but_allows_three_and_restores_outer_level(services):
    state=setup(services,[listener(响应等级='应式'),listener(响应等级='裁断',效果=[counter('counter')])])
    engine,ctx,*_=state
    with engine.root_chain(ctx):
        ctx.chain_level=3
        emit(state)
        assert value(state)==0 and value(state,'counter')==1
        assert ctx.chain_level==3
    assert ctx.chain_level==1


def test_event_without_eligible_response_still_records_and_rebuilds(services):
    state = setup(services, [listener(响应等级='应式')])
    engine, ctx, owner, _ = state
    with engine.root_chain(ctx):
        ctx.chain_level = 3
        emit(state)
        assert value(state) == 0
        assert ctx.event_count == 1 and ctx.events[-1].kind == '恢复后'
        assert ctx.events[-1].values['响应来源等级'] == 3
        assert not ctx.event_stack and ctx.event_depth == 0
        owner.passives.append({'监听键': 'new', '来源能力': 'new', '构筑实例': 'build',
                               '物品编号': 'test', '能力序号': 1,
                               '节点': listener(响应等级='裁断', 效果=[counter('late')])})
        ctx.mark_listener_index_dirty()
        emit(state)
        assert value(state, 'late') == 1
        assert ctx.event_count == 2 and not ctx.event_stack


def test_response_candidates_return_when_outer_level_resumes(services):
    state = setup(services, [
        listener(响应等级='应式', 每条根链最多触发=0),
        listener(响应等级='裁断', 每条根链最多触发=0, 效果=[counter('high')]),
    ])
    engine, ctx, *_ = state
    with engine.root_chain(ctx):
        for level in (3, 2, 3, 1):
            ctx.chain_level = level
            emit(state)
    assert value(state) == 2
    assert value(state, 'high') == 4


def test_counterspell_precedes_response_even_with_lower_priority(services):
    state=setup(services,[listener('恢复前',响应等级='应式',优先级=999,效果=[{'能力':'修改事件数值','方式':'设置','数值':20}]),
                          listener('恢复前',响应等级='裁断',效果=[{'能力':'修改事件数值','方式':'增加','数值':3}])])
    # Check execution ordering directly from the compiled table; existing atomic numeric semantics remain separate.
    table=state[0]._compiled_listeners(state[1])['恢复前']
    assert [entry[6]['响应等级'] for entry in table]==['裁断','应式']
    assert emit(state, '恢复前').amount == 20


def test_tail_accumulates_then_redeems_once_and_does_not_repeat_original_event(services):
    gate={'能力':'数值条件','左值':{'能力':'读取数值','来源':'构筑计量',
          '目标':{'能力':'选择目标','范围':'自身'},'计量':'charge'},'比较':'大于等于','右值':3}
    state=setup(services,[listener(每条根链最多触发=3,效果=[counter('charge')]),
                          listener(结算阶段='链尾',条件=[gate],效果=[counter('reward',10)])])
    engine,ctx,*_=state
    with engine.root_chain(ctx):
        emit(state); emit(state); emit(state)
        assert value(state)==0
    assert value(state)==10 and value(state,'charge')==3
    assert sum(e.kind=='恢复后' for e in ctx.events)==3
    assert not ctx.chain_pending and not ctx.chain_active


def test_tail_and_budget_roll_back_together(services):
    state=setup(services,[listener(结算阶段='链尾')])
    engine,ctx,*_=state
    with engine.root_chain(ctx):
        snapshot=engine._transaction_snapshot(ctx)
        emit(state)
        assert len(ctx.chain_pending)==1
        engine._restore_transaction(ctx,snapshot)
        assert not ctx.chain_pending and not ctx.chain_queued and not ctx.chain_counts
        emit(state)
    assert value(state)==1


def test_immediate_budget_rolls_back(services):
    state=setup(services,[listener()])
    engine,ctx,*_=state
    with engine.root_chain(ctx):
        snapshot=engine._transaction_snapshot(ctx)
        emit(state)
        assert value(state)==1
        engine._restore_transaction(ctx,snapshot)
        emit(state)
        assert value(state)==1


def test_same_event_source_root_limit_preserves_distinct_sources_and_rolls_back(services):
    state = setup(services, [listener(
        观察角色='承受者', 每条根链最多触发=3,
        同一事件来源每条根链最多触发=1,
        效果=[counter('source-limited')],
    )])
    engine, context, _, enemy = state
    other = Fighter(id='X', name='丙', attributes={'血气上限': 100}, health=100, spirit=0)

    with engine.root_chain(context):
        snapshot = engine._transaction_snapshot(context)
        emit_from(state, enemy)
        emit_from(state, enemy)
        assert value(state, 'source-limited') == 1
        assert sum(context.chain_source_counts.values()) == 1

        engine._restore_transaction(context, snapshot)
        assert not context.chain_source_counts
        emit_from(state, enemy)
        emit_from(state, enemy)
        emit_from(state, other)
        emit_from(state, other)
        emit_from(state, enemy)
        assert value(state, 'source-limited') == 2
        assert sum(context.chain_source_counts.values()) == 2


def test_failed_condition_does_not_consume_same_event_source_limit(services):
    condition = {'能力': '数值条件',
                 '左值': {'能力': '读取数值', '来源': '事件事实', '事实': '原始数值'},
                 '比较': '大于', '右值': 5}
    state = setup(services, [listener(
        观察角色='承受者', 每条根链最多触发=3,
        同一事件来源每条根链最多触发=1, 条件=[condition],
        效果=[counter('source-limited')],
    )])
    engine, context, _, enemy = state
    with engine.root_chain(context):
        engine._dispatch_event(context, kind='恢复后', source=enemy,
                               target=state[2], amount=1)
        engine._dispatch_event(context, kind='恢复后', source=enemy,
                               target=state[2], amount=10)
        assert value(state, 'source-limited') == 1
        assert sum(context.chain_source_counts.values()) == 1


def test_nested_rollback_preserves_following_listener_budget(services):
    failed_transaction = {
        '能力': '事务执行',
        '效果': [counter('temporary'), {
            '能力': '消耗资源', '目标': {'能力': '选择目标', '范围': '自身'},
            '资源': '精神', '数值': 1000, '不足时是否失败': True,
        }],
    }
    state = setup(services, [listener(效果=[failed_transaction]), listener()])
    engine, ctx, *_ = state
    with engine.root_chain(ctx):
        emit(state)
        assert value(state, 'temporary') == 0
        assert value(state) == 1
        emit(state)
        assert value(state) == 1
        assert sum(ctx.chain_counts.values()) == 2
        assert sum(ctx.battle_trigger_counts.values()) == 2


def test_retired_listener_does_not_execute_tail(services):
    state=setup(services,[listener(结算阶段='链尾')])
    engine,ctx,owner,_=state
    with engine.root_chain(ctx):
        emit(state)
        owner.passives=[]
        ctx.mark_listener_index_dirty()
    assert value(state)==0


def test_rules_unique_per_owner_and_build_with_stable_budget_ids(services):
    state=setup(services,[])
    engine,ctx,owner,enemy=state
    rule={'能力':'修改战场规则','名称':'甲规则','方式':'添加','重复处理':'同源唯一',
          '规则':{'监听':[listener(每场战斗最多触发=1)]}}
    ctx.current_build_instance='build'
    assert engine._ability_modify_battle_rule(ctx,owner,owner,rule,1)
    assert not engine._ability_modify_battle_rule(ctx,owner,owner,rule,1)
    assert engine._ability_modify_battle_rule(ctx,enemy,enemy,rule,1)
    emit(state)
    identity=ctx.battle_rules[1]['运行编号']
    ctx.battle_rules.pop(0)
    ctx.mark_listener_index_dirty()
    assert ctx.battle_rules[0]['运行编号']==identity
    assert engine._ability_modify_battle_rule(ctx,owner,owner,rule,1)
    assert ctx.battle_rules[-1]['运行编号']>identity
    emit(state)
    assert value(state)==2  # A new rule does not inherit a deleted rule's spent battle allowance.


def test_chain_exception_restores_lifecycle(services):
    state=setup(services,[])
    engine,ctx,*_=state
    with pytest.raises(RuntimeError):
        with engine.root_chain(ctx):
            ctx.chain_level=3
            raise RuntimeError('abort')
    assert not ctx.chain_active and ctx.chain_level==1 and not ctx.chain_pending


def test_counterspell_child_events_cannot_start_lower_speed_response(services):
    heal={'能力':'恢复资源','目标':{'能力':'选择目标','范围':'自身'},'资源':'精神','数值':10}
    state=setup(services,[listener(响应等级='裁断',效果=[heal]),
                          listener('资源恢复后',响应等级='应式'),
                          listener('资源恢复后',响应等级='裁断',效果=[counter('high')])])
    emit(state)
    assert state[2].spirit==10
    assert value(state)==0 and value(state,'high')==1
    assert state[1].chain_serial==1


def test_tail_new_jobs_drain_once_in_same_root(services):
    heal={'能力':'恢复资源','目标':{'能力':'选择目标','范围':'自身'},'资源':'精神','数值':10}
    state=setup(services,[listener(结算阶段='链尾',效果=[heal]),
                          listener('资源恢复后',结算阶段='链尾')])
    emit(state)
    assert value(state)==1 and state[2].spirit==10 and state[1].chain_serial==1


def test_tail_queue_survives_unrelated_transaction_restore(services):
    state=setup(services,[listener(结算阶段='链尾')])
    engine,ctx,*_=state
    with engine.root_chain(ctx):
        emit(state)
        snapshot=engine._transaction_snapshot(ctx)
        engine._restore_transaction(ctx,snapshot)
    assert value(state)==1


def test_candidate_pruning_resets_on_next_root_and_rollback(services):
    state=setup(services,[listener(效果=[counter(str(i))]) for i in range(12)])
    engine,ctx,*_=state
    with engine.root_chain(ctx):
        snapshot=engine._transaction_snapshot(ctx)
        emit(state); emit(state)
        assert all(value(state,str(i))==1 for i in range(12))
        engine._restore_transaction(ctx,snapshot)
        emit(state)
        assert all(value(state,str(i))==1 for i in range(12))
    emit(state)
    assert all(value(state,str(i))==2 for i in range(12))


@pytest.mark.parametrize('node', [
    listener('恢复前',响应等级='应式',结算阶段='链尾'),
    listener('受到致命伤害',结算阶段='链尾'),
    listener(响应等级='裁断',结算阶段='链尾'),
    listener(结算阶段='链尾',每条根链最多触发=2),
    listener(结算阶段='链尾',效果=[{'能力':'取消事件'}]),
    listener(结算阶段='链尾',同一事件来源每条根链最多触发=1),
])
def test_invalid_tail_declarations_rejected_at_validation(services,node):
    from game.core.combat.schema import RuleSchemaValidator, RuleSchemaError
    from game.core.combat.executors import EXECUTOR_CATEGORIES
    catalog=services.combat._engine.catalog
    validator=RuleSchemaValidator(abilities=catalog.abilities, executor_categories=EXECUTOR_CATEGORIES,
                                  attributes=catalog.attributes,resources=catalog.resources,events=catalog.events)
    with pytest.raises(RuleSchemaError):
        validator.validate_node(node,'测试监听')


def test_fatal_guard_is_immediate_and_revive_keeps_same_root(services):
    node=listener('受到致命伤害',观察角色='承受者',响应等级='裁断',
                  效果=[{'能力':'抵挡致命伤害','保留血气':7}])
    state=setup(services,[node])
    engine,ctx,owner,enemy=state
    with engine.root_chain(ctx):
        def hit():
            engine._apply_damage(ctx,enemy,owner,200,label='测试致命',defense_rule='真实',
                                 can_critical=False,can_block=False,allow_reactions=False)
        hit()
        assert owner.health==7
        hit()
        assert not owner.alive
        assert engine._ability_revive(ctx,enemy,owner,{'能力':'复活','目标':{
            '能力':'选择目标','范围':'当前目标','生存状态':'死亡'},'血气百分比':25},1)
        assert owner.health==25 and ctx.chain_serial==1
        hit()
        assert not owner.alive  # Revival cannot refresh a spent guard budget in this chain.
