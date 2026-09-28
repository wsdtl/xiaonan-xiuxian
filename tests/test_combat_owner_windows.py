"""显式的持有者主行动间隔名额，不给未声明的扩展监听附加限制。"""
import pytest

from game.core.combat.models import EventFrame
from test_combat_chains import counter, emit, listener, setup, value
from test_combat_entry_surfaces import services


@pytest.mark.parametrize('fields',[{}, {'自身行动间隔最多触发':0}])
def test_undeclared_or_zero_owner_budget_remains_unlimited(services,fields):
    state=setup(services,[listener(每条根链最多触发=0,**fields)])
    for _ in range(5):emit(state)
    assert value(state)==5
    assert state[1].support_window=={}


def test_other_global_actions_and_new_roots_do_not_refresh_owner_budget(services):
    state=setup(services,[listener(自身行动间隔最多触发=2)])
    for _ in range(6):
        state[1].action_number+=1
        state[1].trigger_counts.clear()
        emit(state)
    assert value(state)==2
    assert sum(state[1].support_window.values())==2


def test_duplicate_build_instances_share_owner_declaration_budget(services):
    state=setup(services,[listener(自身行动间隔最多触发=2)])
    engine,ctx,owner,_=state
    owner.passives.append({**owner.passives[0],'构筑实例':'second-copy'})
    ctx.rebuild_indexes()
    for _ in range(5):emit(state)
    assert sum(ctx.ability_counters.values())==2
    assert len(ctx.support_window)==1


def test_distinct_owners_have_separate_budgets(services):
    state=setup(services,[listener(阵营关系='任意',自身行动间隔最多触发=2)])
    _,ctx,owner,enemy=state
    enemy.passives=list(owner.passives)
    ctx.rebuild_indexes()
    for _ in range(5):emit(state)
    assert value(state)==2
    assert ctx.ability_counters[(enemy.id,'build','reward')]==2
    assert len(ctx.support_window)==2


def test_only_acting_owners_window_resets_before_action_start(services,monkeypatch):
    state=setup(services,[listener(自身行动间隔最多触发=1)])
    engine,ctx,owner,enemy=state
    emit(state)
    assert value(state)==1
    class ActionBoundary(Exception):pass
    def stop_after_action_start(context,actor):raise ActionBoundary
    monkeypatch.setattr(engine,'_recover_at_action_start',stop_after_action_start)
    with pytest.raises(ActionBoundary):engine._take_action(ctx,enemy)
    emit(state)
    assert value(state)==1
    with pytest.raises(ActionBoundary):engine._take_action(ctx,owner)
    assert ctx.support_window=={}
    emit(state)
    assert value(state)==2


def test_owner_budget_snapshot_can_be_restored_repeatedly(services):
    state=setup(services,[listener(自身行动间隔最多触发=2)])
    engine,ctx,*_=state
    emit(state)
    saved=engine._transaction_snapshot(ctx)
    for _ in range(2):
        emit(state);emit(state)
        assert value(state)==2
        engine._restore_transaction(ctx,saved)
        assert value(state)==1 and sum(ctx.support_window.values())==1
    assert sum(saved['support_window'].values())==1


def test_false_condition_preserves_owner_budget(services):
    gate={'能力':'数值条件','左值':{'能力':'读取数值','来源':'本次数值'},'比较':'大于','右值':0}
    state=setup(services,[listener(自身行动间隔最多触发=1,条件=[gate])])
    emit(state,amount=0)
    assert state[1].support_window=={}
    emit(state,amount=10)
    assert value(state)==1


def test_pruned_owner_budgets_return_after_rollback_and_window_refresh(services,monkeypatch):
    state=setup(services,[listener(自身行动间隔最多触发=1,每条根链最多触发=0) for _ in range(10)])
    engine,ctx,owner,_=state
    saved=engine._transaction_snapshot(ctx)
    emit(state)
    frame=EventFrame('恢复后',owner,owner,{'行动者':owner.id})
    with engine.root_chain(ctx):
        assert engine._listeners_for(ctx,'恢复后',frame).available(ctx)==[]
    engine._restore_transaction(ctx,saved)
    emit(state)
    assert value(state)==10
    class ActionBoundary(Exception):pass
    def stop(context,actor):raise ActionBoundary
    monkeypatch.setattr(engine,'_recover_at_action_start',stop)
    with pytest.raises(ActionBoundary):engine._take_action(ctx,owner)
    emit(state)
    assert value(state)==20
