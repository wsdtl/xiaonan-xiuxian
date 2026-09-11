"""由原子能力 JSON 驱动的通用战斗执行器。"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

from .contracts import BattleEvent
from .models import CombatObject, EventFrame, Fighter, Skill, StatusState


class AbilityRuntime:
    """只实现组合语义，不决定具体功法内容。"""

    MAX_EVENT_DEPTH = 32
    MAX_ABILITY_DEPTH = 64
    MAX_REPEAT = 100
    MAX_TRIGGERED_SKILLS = 8

    def _execute_mechanism(
        self,
        context,
        source: Fighter,
        target: Fighter,
        effect: Mapping[str, Any],
        multiplier: float = 1.0,
        *,
        event_amount: float = 0.0,
        event_values: Mapping[str, Any] | None = None,
        tags: tuple[str, ...] = (),
    ) -> bool:
        depth_limit = int(self.catalog.action_rules.get("能力链深度上限", self.MAX_ABILITY_DEPTH))
        if context.ability_depth >= depth_limit:
            raise RuntimeError("战斗能力链超过安全深度")
        node = self.catalog.parse_node(effect)
        effective = dict(effect)
        if (
            node.executor in {"造成伤害", "恢复资源"}
            and "属性构成" not in effective
            and context.current_element_composition
        ):
            effective["属性构成"] = dict(context.current_element_composition)
        handler = self._ability_handlers.get(node.executor)
        if handler is None:
            raise ValueError(f"战斗核心未实现执行器：{node.executor or '<空>'}")
        before_events = len(context.events)
        previous_result = context.last_result
        context.ability_depth += 1
        try:
            result = handler(
                context,
                source,
                target,
                effective,
                multiplier,
                event_amount=event_amount,
                event_values=dict(event_values or {}),
                tags=tuple(tags),
            )
        finally:
            context.ability_depth -= 1
        success = True if result is None else bool(result)
        details = context.last_result if context.last_result is not previous_result else {}
        context.last_result = {
            **details,
            "成功": success,
            "新增事件数": len(context.events) - before_events,
            "能力": node.ability,
            "执行器": node.executor,
        }
        if node.category == "效果" and node.executor not in {"回放效果", "保存结果"}:
            context.effect_history.append(
                {
                    "来源": source.id,
                    "目标": target.id,
                    "节点": copy.deepcopy(effective),
                    "倍率": multiplier,
                    "成功": success,
                }
            )
            del context.effect_history[:-100]
        return success

    def _run_effects(self, context, source, target, effects, multiplier, **kwargs) -> bool:
        for child in effects or ():
            if not self._execute_mechanism(
                context, source, target, dict(child), multiplier, **kwargs
            ):
                return False
        return True

    def _ability_sequence(self, context, source, target, effect, multiplier, **kwargs):
        return self._run_effects(
            context, source, target, effect.get("效果"), multiplier, **kwargs
        )

    def _ability_conditional(self, context, source, target, effect, multiplier, **kwargs):
        allowed = self._conditions_allow(
            context,
            source,
            target,
            effect.get("条件") or (),
            kwargs.get("event_amount", 0.0),
            kwargs.get("event_values") or {},
            kwargs.get("tags") or (),
        )
        branch = effect.get("成立效果" if allowed else "不成立效果") or ()
        return self._run_effects(context, source, target, branch, multiplier, **kwargs)

    def _ability_random(self, context, source, target, effect, multiplier, **kwargs):
        options = list(effect.get("选项") or ())
        count = min(len(options) if not effect.get("是否放回") else self.MAX_REPEAT, max(0, int(effect.get("抽取数量", 1))))
        if not options or count <= 0:
            return False
        chosen = (
            [context.rng.choice(options) for _ in range(count)]
            if effect.get("是否放回")
            else context.rng.sample(options, count)
        )
        return self._run_effects(context, source, target, chosen, multiplier, **kwargs)

    def _ability_iterate(self, context, source, target, effect, multiplier, **kwargs):
        destinations = self._select_targets(context, source, target, effect.get("目标"))
        if not destinations:
            return False
        ok = True
        for destination in destinations:
            ok = self._run_effects(
                context, source, destination, effect.get("效果"), multiplier, **kwargs
            ) and ok
        return ok

    def _ability_repeat(self, context, source, target, effect, multiplier, **kwargs):
        count = int(
            self._resolve_value(
                context,
                effect.get("次数", 1),
                source,
                target,
                kwargs.get("event_amount", 0.0),
                kwargs.get("event_values") or {},
            )
        )
        count = max(0, min(self.MAX_REPEAT, count))
        if count == 0:
            return False
        for index in range(count):
            context.saved_results["当前重复序号"] = index + 1
            if not self._run_effects(
                context, source, target, effect.get("效果"), multiplier, **kwargs
            ) and effect.get("失败时停止", True):
                return False
        return True

    def _ability_attempt(self, context, source, target, effect, multiplier, **kwargs):
        success = self._run_effects(
            context, source, target, effect.get("尝试效果"), multiplier, **kwargs
        )
        branch = effect.get("成功效果" if success else "失败效果") or ()
        self._run_effects(context, source, target, branch, multiplier, **kwargs)
        return success

    def _ability_transaction(self, context, source, target, effect, multiplier, **kwargs):
        snapshot = self._transaction_snapshot(context)
        if self._run_effects(
            context, source, target, effect.get("效果"), multiplier, **kwargs
        ):
            return True
        self._restore_transaction(context, snapshot)
        self._run_effects(
            context, source, target, effect.get("失败效果"), multiplier, **kwargs
        )
        return False

    @staticmethod
    def _transaction_snapshot(context) -> dict[str, Any]:
        return {
            "fighters": {
                fighter.id: copy.deepcopy(fighter.__dict__)
                for fighter in context.fighters
            },
            "left_ids": [fighter.id for fighter in context.left_team],
            "right_ids": [fighter.id for fighter in context.right_team],
            "records": copy.deepcopy(context.records),
            "relations": copy.deepcopy(context.relations),
            "objects": copy.deepcopy(context.combat_objects),
            "rules": copy.deepcopy(context.battle_rules),
            "progress": copy.deepcopy(context.action_progress),
            "counters": copy.deepcopy(context.ability_counters),
            "saved": copy.deepcopy(context.saved_results),
            "event_count": len(context.events),
            "history_count": len(context.effect_history),
            "rng_state": context.rng.getstate(),
            "trigger_counts": copy.deepcopy(context.trigger_counts),
            "battle_trigger_counts": copy.deepcopy(context.battle_trigger_counts),
            "judgement_overrides": copy.deepcopy(context.judgement_overrides),
            "action_intent": copy.deepcopy(context.action_intent),
            "last_result": copy.deepcopy(context.last_result),
            "triggered_skill_depth": context.triggered_skill_depth,
            "frames": [
                {
                    "frame": frame,
                    "kind": frame.kind,
                    "source": frame.source,
                    "target": frame.target,
                    "facts": copy.deepcopy(frame.facts),
                    "tags": set(frame.tags),
                    "cancelled": frame.cancelled,
                    "transformed_kind": frame.transformed_kind,
                    "original_kind": frame.original_kind,
                }
                for frame in context.event_stack
            ],
            "summon_serial": context.summon_serial,
        }

    @staticmethod
    def _restore_transaction(context, snapshot: Mapping[str, Any]) -> None:
        current = {fighter.id: fighter for fighter in context.fighters}
        for fighter_id, values in snapshot["fighters"].items():
            fighter = current.get(fighter_id)
            if fighter is None:
                continue
            for key, value in values.items():
                setattr(fighter, key, copy.deepcopy(value))
        context.left_team[:] = [current[value] for value in snapshot["left_ids"] if value in current]
        context.right_team[:] = [current[value] for value in snapshot["right_ids"] if value in current]
        context.rebuild_indexes()
        context.records = copy.deepcopy(snapshot["records"])
        context.relations = copy.deepcopy(snapshot["relations"])
        context.combat_objects = copy.deepcopy(snapshot["objects"])
        context.battle_rules = copy.deepcopy(snapshot["rules"])
        context.mark_listener_index_dirty()
        context.action_progress = copy.deepcopy(snapshot["progress"])
        context.ability_counters = copy.deepcopy(snapshot["counters"])
        context.saved_results = copy.deepcopy(snapshot["saved"])
        del context.events[snapshot["event_count"]:]
        del context.effect_history[snapshot["history_count"]:]
        context.rng.setstate(snapshot["rng_state"])
        context.trigger_counts = copy.deepcopy(snapshot["trigger_counts"])
        context.battle_trigger_counts = copy.deepcopy(snapshot["battle_trigger_counts"])
        context.judgement_overrides = copy.deepcopy(snapshot["judgement_overrides"])
        context.action_intent = copy.deepcopy(snapshot["action_intent"])
        context.last_result = copy.deepcopy(snapshot["last_result"])
        context.triggered_skill_depth = snapshot["triggered_skill_depth"]
        context.summon_serial = snapshot["summon_serial"]
        for saved in snapshot["frames"]:
            frame = saved["frame"]
            for key in ("kind", "source", "target", "cancelled", "transformed_kind", "original_kind"):
                setattr(frame, key, saved[key])
            frame.facts = copy.deepcopy(saved["facts"])
            frame.tags = set(saved["tags"])

    @staticmethod
    def _ability_listener(*_args, **_kwargs):
        return True

    def _compiled_listeners(self, context):
        """Compile listeners by event for the current structural battle state."""

        if not context.listener_index_dirty:
            return context.listener_index

        listener_order = tuple(self.catalog.timing["事件监听"]["排序"])
        grouped: dict[
            str,
            list[tuple[tuple[Any, ...], Fighter, str, str, str, Mapping[str, Any], Mapping[str, float], Mapping[str, Any]]],
        ] = {}
        participant_order = context.fighter_order

        def add_listener(
            owner: Fighter,
            listener_id: str,
            node: Mapping[str, Any],
            *,
            source_ability: str = "",
            settlement_order: int = 1,
            build_order: int = 0,
            item_id: str = "",
            ability_order: int = 0,
            effect_order: int = 0,
            source_category: str = "功法",
            build_instance: str = "",
            element_composition: Mapping[str, float] | None = None,
        ) -> None:
            event_name = str(node.get("事件") or "")
            if not event_name:
                return
            values = {
                "来源层级升序": self._source_layer(source_category),
                "监听优先级降序": -int(node.get("优先级", 0)),
                "结算顺序升序": int(settlement_order),
                "参战位序": participant_order.get(owner.id, len(participant_order)),
                "装配位序": int(build_order),
                "物品编号": str(item_id),
                "能力序号": (int(ability_order), int(effect_order)),
            }
            activation_id = (
                f"{build_instance}:{item_id}:{listener_id}:{ability_order}:{effect_order}"
                if item_id
                else f"{build_instance}:{listener_id}"
            )
            key = tuple(values[field] for field in listener_order) + (activation_id,)
            grouped.setdefault(event_name, []).append(
                (
                    key,
                    owner,
                    activation_id,
                    str(source_ability),
                    str(build_instance),
                    node,
                    dict(element_composition or {"无相": 100}),
                )
            )

        for owner in context.fighters:
            for passive in owner.passives:
                for mechanism_id, node in self._passive_listener_nodes(passive):
                    add_listener(
                        owner,
                        mechanism_id,
                        node,
                        source_ability=str(passive.get("来源能力") or ""),
                        settlement_order=int(passive.get("结算顺序", 1)),
                        build_order=int(passive.get("装配位序", 0)),
                        item_id=str(passive.get("物品编号") or ""),
                        ability_order=int(passive.get("能力序号", 0)),
                        effect_order=int(passive.get("效果序号", 0)),
                        source_category=str(passive.get("来源类别") or "功法"),
                        build_instance=str(passive.get("构筑实例") or ""),
                        element_composition=passive.get("属性构成"),
                    )
            for status in owner.statuses:
                item_id = str(status.values.get("战丹编号") or status.name)
                for index, node in enumerate(status.listeners):
                    add_listener(
                        owner,
                        f"{status.name}:{index}",
                        node,
                        source_ability=status.source_ability or status.name,
                        item_id=item_id,
                        ability_order=index,
                        source_category="战丹",
                        build_instance=str(status.build_instance or ""),
                    )
        if context.field is not None:
            field = context.field
            for index, node in enumerate(field.stage.passive_abilities):
                add_listener(
                    field.source,
                    f"环境:{field.definition.environment_id}:{field.stage_index}:{index}",
                    node,
                    source_ability=field.stage.name,
                    settlement_order=0,
                    item_id=f"环境:{field.definition.environment_id}",
                    ability_order=index,
                    source_category="战场环境",
                )
        for obj in context.combat_objects.values():
            if not obj.active:
                continue
            owner = context.fighter_by_id(obj.owner_id) or context.left
            for index, node in enumerate(obj.listeners):
                add_listener(
                    owner,
                    f"{obj.id}:{index}",
                    node,
                    source_ability=obj.name,
                    item_id=obj.id,
                    ability_order=index,
                    source_category="战斗对象",
                )
        for index, rule in enumerate(context.battle_rules):
            owner = context.fighter_by_id(str(rule.get("来源") or "")) or context.left
            for listener_index, node in enumerate(rule.get("监听") or ()):
                add_listener(
                    owner,
                    f"战场:{index}:{listener_index}",
                    node,
                    source_ability=str(rule.get("名称") or "战场规则"),
                    item_id=f"战场:{index}",
                    ability_order=listener_index,
                    source_category="战场规则",
                )

        context.listener_index = {
            event_name: tuple(sorted(values, key=lambda item: item[0]))
            for event_name, values in grouped.items()
        }
        context.listener_index_dirty = False
        return context.listener_index

    def _source_layer(self, source: str) -> int:
        layers = self.catalog.timing.get("来源层级") or ()
        for entry in layers:
            if str(entry.get("来源") or "") == str(source):
                return int(entry["序位"])
        raise ValueError(f"战斗时序未登记来源层级：{source}")

    def _dispatch_event(self, context, *, kind, source, target, amount=0.0, values=None, tags=(), record=True):
        depth_limit = int(self.catalog.action_rules.get("事件链深度上限", self.MAX_EVENT_DEPTH))
        if context.event_depth >= depth_limit:
            raise RuntimeError("战斗事件链超过安全深度")
        self.catalog.require_event(kind)
        facts = dict(values or {})
        facts.setdefault("事件", kind)
        facts.setdefault("来源", source.id)
        facts.setdefault("承受者", target.id)
        facts.setdefault("行动者", source.id)
        facts.setdefault("原始数值", float(amount))
        facts.setdefault("当前数值", float(amount))
        frame = EventFrame(kind, source, target, facts, set(tags))
        context.event_stack.append(frame)
        context.event_depth += 1
        try:
            listeners = self._compiled_listeners(context).get(kind, ())
            for _, owner, activation_id, source_ability, build_instance, node, composition in listeners:
                if not self._listener_relation_matches(context, owner, frame, node):
                    continue
                if not self._conditions_allow(
                    context, owner, frame.target, node.get("条件") or (), frame.amount, frame.facts, tuple(frame.tags)
                ):
                    continue
                activation = (owner.id, activation_id)
                if activation in context.trigger_stack:
                    continue
                per_action = int(node.get("每次行动最多触发", 0) or 0)
                per_battle = int(node.get("每场战斗最多触发", 0) or 0)
                if per_action and context.trigger_counts.get(activation, 0) >= per_action:
                    continue
                if per_battle and context.battle_trigger_counts.get(activation, 0) >= per_battle:
                    continue
                context.trigger_counts[activation] = context.trigger_counts.get(activation, 0) + 1
                context.battle_trigger_counts[activation] = context.battle_trigger_counts.get(activation, 0) + 1
                context.trigger_stack.add(activation)
                previous = context.current_ability
                previous_composition = context.current_element_composition
                previous_instance = context.current_build_instance
                context.current_ability = source_ability
                context.current_build_instance = build_instance
                context.current_element_composition = dict(composition)
                try:
                    self._run_effects(
                        context,
                        owner,
                        frame.target,
                        node.get("效果") or (),
                        1.0,
                        event_amount=frame.amount,
                        event_values=frame.facts,
                        tags=tuple(frame.tags),
                    )
                finally:
                    context.current_ability = previous
                    context.current_build_instance = previous_instance
                    context.current_element_composition = previous_composition
                    context.trigger_stack.discard(activation)
            if frame.transformed_kind:
                frame.facts["原事件"] = frame.kind
                frame.facts["事件"] = frame.transformed_kind
            if record and not frame.transformed_kind:
                context.events.append(
                    BattleEvent(
                        turn=context.action_number,
                        kind=frame.transformed_kind or frame.kind,
                        source=frame.source.name,
                        target=frame.target.name,
                        text=frame.transformed_kind or frame.kind,
                        amount=round(frame.amount, 3),
                        values=copy.deepcopy(frame.facts),
                        tags=tuple(sorted(frame.tags)),
                        ability=context.current_ability,
                        source_id=frame.source.id,
                        target_id=frame.target.id,
                    )
                )
            if frame.transformed_kind:
                transformed_chain = [item.kind for item in context.event_stack]
                if frame.transformed_kind in transformed_chain:
                    chain = " -> ".join((*transformed_chain, frame.transformed_kind))
                    raise RuntimeError(f"战斗事件转化形成循环：{chain}")
                converted = self._dispatch_event(
                    context,
                    kind=frame.transformed_kind,
                    source=frame.source,
                    target=frame.target,
                    amount=frame.amount,
                    values=frame.facts,
                    tags=tuple(frame.tags),
                    record=record,
                )
                converted.original_kind = frame.original_kind
                return converted
            return frame
        finally:
            context.event_depth -= 1
            context.event_stack.pop()

    @staticmethod
    def _passive_listener_nodes(
        passive: Mapping[str, Any]
    ) -> tuple[tuple[str, dict[str, Any]], ...]:
        """只登记监听节点；被动槽位里的非监听效果不参与事件索引。

        `tools/架构审查/检查构筑形状.py` 会把这类效果列出来，它们从未生效过。
        """

        raw = passive.get("节点")
        if not isinstance(raw, Mapping):
            raise TypeError("被动技能缺少监听节点")
        if str(raw.get("能力") or "") != "监听事件":
            return ()
        return ((str(passive.get("监听键") or "内联被动"), dict(raw)),)

    def _listener_relation_matches(self, context, owner, frame, node) -> bool:
        role = str(node.get("观察角色") or "来源")
        observed = {
            "来源": frame.source,
            "承受者": frame.target,
            "行动者": context.fighter_by_id(str(frame.facts.get("行动者") or "")) or frame.source,
        }.get(role)
        if observed is None:
            raise ValueError(f"未知事件观察角色：{role}")
        relation = str(node.get("阵营关系") or "自身")
        if relation == "自身":
            return observed is owner
        if relation == "其他己方":
            return observed is not owner and observed.side == owner.side
        if relation == "任意己方":
            return observed.side == owner.side
        if relation == "任意敌方":
            return observed.side != owner.side
        if relation == "任意":
            return True
        raise ValueError(f"未知阵营关系：{relation}")

    def _conditions_allow(self, context, source, target, conditions, event_amount, event_values, tags):
        for raw in conditions or ():
            condition = dict(raw)
            executor = self.catalog.parse_node(condition).executor
            handler = self._condition_handlers.get(executor)
            if handler is None:
                raise ValueError(f"战斗核心未实现条件执行器：{executor or '<空>'}")
            if not handler(context, source, target, condition, event_amount, event_values, tags):
                return False
        return True

    def _condition_probability(self, context, source, target, condition, *_):
        chance = self._resolve_value(context, condition.get("概率", 0), source, target, 0, {}) / 100.0
        return self._judgement(context, "概率", chance)

    def _condition_numeric(self, context, source, target, condition, event_amount, event_values, _tags):
        left = self._resolve_value(context, condition.get("左值"), source, target, event_amount, event_values)
        right = self._resolve_value(context, condition.get("右值"), source, target, event_amount, event_values)
        return self._compare(left, right, str(condition.get("比较") or "等于"))

    def _condition_status(self, context, source, target, condition, *_):
        destinations = self._select_targets(context, source, target, condition.get("目标"))
        name = str(condition.get("状态") or "")
        count = sum(status.stacks for fighter in destinations for status in fighter.statuses if not name or status.name == name)
        relation = str(condition.get("比较") or "存在")
        if relation == "存在":
            return count > 0
        if relation == "不存在":
            return count == 0
        return self._compare(count, float(condition.get("层数", 1)), relation.removeprefix("层数"))

    def _condition_type(self, context, source, target, condition, _amount, event_values, _tags):
        subject = source if str(condition.get("对象") or "目标") == "来源" else target
        kind = str(condition.get("类型") or "")
        expected = str(condition.get("值") or "")
        if kind == "参战身份":
            return subject.combatant_type == expected or expected in subject.tags
        if kind == "形态":
            return subject.form == expected
        if kind == "性别":
            return subject.gender == expected
        aliases = {"资源类型": "资源", "行动类型": "行动类型", "技能类型": "技能类型"}
        return str(event_values.get(aliases.get(kind, kind), "")) == expected

    def _condition_combined(self, context, source, target, condition, amount, values, tags):
        results = [self._conditions_allow(context, source, target, (item,), amount, values, tags) for item in condition.get("条件") or ()]
        relation = str(condition.get("关系") or "全部成立")
        if relation == "全部成立":
            return all(results)
        if relation == "任一成立":
            return any(results)
        if relation == "全部不成立":
            return not any(results)
        raise ValueError(f"未知组合条件关系：{relation}")

    def _condition_tags(self, context, source, target, condition, _amount, event_values, event_tags):
        obj = str(condition.get("对象") or "事件")
        actual = set(event_tags)
        if obj == "来源":
            actual = source.tags
        elif obj == "目标":
            actual = target.tags
        elif obj == "状态":
            actual = {tag for status in target.statuses for tag in status.tags}
        elif obj == "技能":
            skill = self._skill_by_key(source, str(event_values.get("技能键") or source.current_skill))
            actual = set(skill.tags if skill else ())
        expected = {str(value) for value in condition.get("标签") or ()}
        relation = str(condition.get("关系") or "包含任一")
        if relation == "包含任一":
            return bool(actual & expected)
        if relation == "包含全部":
            return expected <= actual
        if relation == "全部不含":
            return not bool(actual & expected)
        if relation == "为空":
            return not actual
        if relation == "数量至少":
            return len(actual) >= max(1, int(condition.get("数量", 1)))
        raise ValueError(f"未知标签关系：{relation}")

    @staticmethod
    def _compare(left: float, right: float, relation: str) -> bool:
        return {
            "等于": left == right,
            "不等于": left != right,
            "大于": left > right,
            "大于等于": left >= right,
            "小于": left < right,
            "小于等于": left <= right,
        }.get(relation, False)

    def _ability_damage(self, context, source, target, effect, multiplier, **kwargs):
        destinations = self._select_targets(context, source, target, effect.get("目标"))
        if not destinations:
            return False
        success = False
        for destination in destinations:
            amount = self._resolve_value(context, effect.get("数值"), source, destination, kwargs.get("event_amount", 0), kwargs.get("event_values") or {}) * multiplier
            amount *= self._element_multiplier(context, source, destination, effect)
            if source.current_skill and str(effect.get("伤害形式") or "直接") == "直接":
                amount *= max(0.0, 1.0 + self._percent(source, "技能威力"))
            resolution = self._apply_damage(
                context,
                source,
                destination,
                amount,
                label=context.current_ability or str(effect.get("名称") or "伤害"),
                damage_form=str(effect.get("伤害形式") or "直接"),
                defense_rule=str(effect.get("防御规则") or "普通"),
                can_miss=bool(effect.get("能否闪避", False)),
                can_critical=bool(effect.get("能否暴击", True)),
                can_block=bool(effect.get("能否格挡", True)),
                tags=tuple(str(value) for value in effect.get("标签") or ()),
            )
            success = resolution.actual_damage > 0 or success
            if resolution.actual_damage > 0:
                self._mark_team_synergy(context, source, effect)
            context.last_result = {**context.last_result, **resolution.values()}
        return success

    def _ability_recover_resource(self, context, source, target, effect, multiplier, **kwargs):
        requested_resource = str(effect.get("资源") or "血气")
        changed = False
        attempted = False
        for destination in self._select_targets(context, source, target, effect.get("目标")):
            amount = max(0.0, self._resolve_value(context, effect.get("数值"), source, destination, kwargs.get("event_amount", 0), kwargs.get("event_values") or {}) * multiplier)
            amount *= self._element_multiplier(context, source, destination, effect)
            if requested_resource == "血气":
                amount *= max(0.0, 1.0 + self._percent(source, "治疗加成"))
            elif requested_resource == "护盾":
                amount *= max(0.0, 1.0 + self._percent(source, "护盾加成"))
            before, maximum = self._resource_values(destination, requested_resource)
            event = "恢复前" if requested_resource == "血气" else "获得护盾前" if requested_resource == "护盾" else "资源恢复前"
            frame = self._dispatch_event(context, kind=event, source=source, target=destination, amount=amount, values={"资源": requested_resource, "变化前数值": before, "上限": maximum}, tags=(*effect.get("标签", ()), "恢复", requested_resource))
            if frame.cancelled:
                continue
            resource = requested_resource
            if frame.kind == "获得护盾前":
                resource = "护盾"
            elif frame.kind == "恢复前":
                resource = "血气"
            destination = frame.target
            if "恢复" in self._immunities(destination):
                continue
            # 恢复已满不是执行失败；后续顺序效果仍必须继续执行。
            attempted = True
            before, maximum = self._resource_values(destination, resource)
            received = max(0.0, frame.amount)
            if resource == "血气":
                received *= max(0.0, 1.0 + self._percent(destination, "受疗加成"))
            elif resource == "护盾":
                received *= max(0.0, 1.0 + self._percent(destination, "受盾加成"))
            applied = min(maximum - before, received)
            self._set_resource(destination, resource, before + applied)
            after_event = "恢复后" if resource == "血气" else "获得护盾后" if resource == "护盾" else "资源恢复后"
            values = {"资源": resource, "变化前数值": before, "变化后数值": before + applied, "实际数值": applied, "溢出数值": max(0.0, received - applied)}
            event_tags = (*frame.tags, "恢复", resource)
            self._dispatch_event(context, kind=after_event, source=source, target=destination, amount=applied, values=values, tags=event_tags)
            self._dispatch_event(context, kind="资源变化后", source=source, target=destination, amount=applied, values=values, tags=(*frame.tags, "增加", resource))
            changed = changed or applied > 0
            if applied > 0:
                self._mark_team_synergy(context, source, effect)
        return changed or attempted

    def _element_multiplier(self, context, source, target, effect):
        composition = effect.get("属性构成")
        if not composition:
            return 1.0
        values = {str(key): float(value) for key, value in dict(composition).items()}
        if not values or "无相" in values and len(values) == 1:
            return 1.0
        source_root = source.five_elements
        target_root = target.five_elements
        rules = self.catalog.five_elements
        generating = {str(item["来源"]): str(item["目标"]) for item in rules.get("相生", ())}
        overcoming = {str(item["来源"]): str(item["目标"]) for item in rules.get("相克", ())}
        root_rules = rules.get("根性倍率", {})
        root_score = sum(
            source_root[element] * weight
            for element, weight in values.items()
            if element in source_root
        ) / 100.0
        root_multiplier = max(
            float(root_rules.get("最低", 0.9)),
            min(
                float(root_rules.get("最高", 1.4)),
                1.0
                + (root_score - float(root_rules.get("基准", 20)))
                * float(root_rules.get("每点修正", 0.005)),
            ),
        )
        multipliers = rules.get("倍率", {})
        relation = 0.0
        total = 0.0
        for element, weight in values.items():
            if element == "无相":
                continue
            for target_element, target_weight in target_root.items():
                if element == target_element:
                    factor = 1.0
                elif generating.get(element) == target_element:
                    factor = float(multipliers.get("相生", 1.03))
                elif overcoming.get(element) == target_element:
                    factor = float(multipliers.get("相克", 1.15))
                elif overcoming.get(target_element) == element:
                    factor = float(multipliers.get("被克", 0.85))
                else:
                    factor = 1.0
                relation += weight * target_weight * factor
                total += weight * target_weight
        result = root_multiplier * (relation / total if total else 1.0)
        for element in values:
            if source.team_synergy.pop(element, 0):
                result *= float(multipliers.get("团队相生", 1.08))
                break
        return result

    def _mark_team_synergy(self, context, source, effect):
        composition = effect.get("属性构成") or {}
        generating = {
            str(item["来源"]): str(item["目标"])
            for item in self.catalog.five_elements.get("相生", ())
        }
        elements = [generating[element] for element in composition if element in generating]
        if not elements:
            return
        element = elements[0]
        for ally in context.allies_of(source, alive=None):
            if ally is source or ally.team_synergy:
                continue
            ally.team_synergy[element] = 1

    def _ability_consume_resource(self, context, source, target, effect, multiplier, **kwargs):
        resource = str(effect.get("资源") or "精神")
        changed = False
        for destination in self._select_targets(context, source, target, effect.get("目标")):
            amount = max(0.0, self._resolve_value(context, effect.get("数值"), source, destination, kwargs.get("event_amount", 0), kwargs.get("event_values") or {}) * multiplier)
            before, _ = self._resource_values(destination, resource)
            frame = self._dispatch_event(context, kind="资源消耗前", source=source, target=destination, amount=amount, values={"资源": resource, "变化前数值": before}, tags=("消耗", resource))
            destination = frame.target
            before, _ = self._resource_values(destination, resource)
            if frame.cancelled or (before < frame.amount and effect.get("不足时是否失败", True)):
                return False
            applied = min(before, max(0.0, frame.amount))
            self._set_resource(destination, resource, before - applied)
            values = {"资源": resource, "变化前数值": before, "变化后数值": before - applied, "实际数值": applied}
            self._dispatch_event(context, kind="资源消耗后", source=source, target=destination, amount=applied, values=values, tags=(*frame.tags, "消耗", resource))
            self._dispatch_event(context, kind="资源变化后", source=source, target=destination, amount=-applied, values=values, tags=(*frame.tags, "减少", resource))
            changed = changed or applied > 0
        return changed

    def _ability_pay_cost(self, context, source, target, effect, multiplier, **kwargs):
        kind = str(effect.get("代价类型") or "资源")
        if kind == "资源":
            return self._ability_consume_resource(context, source, target, effect, multiplier, **kwargs)
        if kind == "状态层数":
            value = {**effect, "层数": effect.get("数值", 1), "不足时是否失败": True}
            return self._ability_modify_status_stacks(context, source, target, value, multiplier, consume=True)
        if kind == "行动条":
            value = {**effect, "方式": "减少"}
            return self._ability_modify_action_progress(context, source, target, value, multiplier, cost=True)
        if kind == "技能冷却":
            value = {**effect, "方式": "增加"}
            return self._ability_modify_cooldown(context, source, target, value, multiplier)
        if kind == "战斗对象":
            return self._ability_remove_object(context, source, target, effect, multiplier)
        raise ValueError(f"未知代价类型：{kind}")

    def _ability_set_resource(self, context, source, target, effect, multiplier, **kwargs):
        resource = str(effect.get("资源") or "血气")
        changed = False
        for destination in self._select_targets(context, source, target, effect.get("目标")):
            before, maximum = self._resource_values(destination, resource)
            value = self._resolve_value(context, effect.get("数值"), source, destination, kwargs.get("event_amount", 0), kwargs.get("event_values") or {}) * multiplier
            after = self._clamp(value, 0, maximum)
            self._set_resource(destination, resource, after)
            changed = changed or before != after
        return changed

    def _ability_transfer_resource(self, context, source, target, effect, multiplier, **kwargs):
        donors = self._select_targets(context, source, target, effect.get("来源目标"))
        receivers = self._select_targets(context, source, target, effect.get("接收目标"))
        if not donors or not receivers:
            return False
        donor, receiver = donors[0], receivers[0]
        source_resource = str(effect.get("来源资源") or "血气")
        target_resource = str(effect.get("接收资源") or source_resource)
        if donor is receiver and source_resource == target_resource:
            return False
        amount = max(0.0, self._resolve_value(context, effect.get("数值"), source, donor, kwargs.get("event_amount", 0), kwargs.get("event_values") or {}) * multiplier)
        before, _ = self._resource_values(donor, source_resource)
        if before < amount and effect.get("不足时是否失败", True):
            return False
        paid = min(before, amount)
        receiver_before, receiver_max = self._resource_values(receiver, target_resource)
        applied = min(receiver_max - receiver_before, paid)
        self._set_resource(donor, source_resource, before - paid)
        self._set_resource(receiver, target_resource, receiver_before + applied)
        return applied > 0

    def _ability_add_status(self, context, source, target, effect, multiplier, **_):
        changed = False
        for destination in self._select_targets(context, source, target, effect.get("目标")):
            definition = copy.deepcopy(dict(effect.get("状态") or {}))
            frame = self._dispatch_event(context, kind="添加状态前", source=source, target=destination, values={"状态": definition.get("名称", ""), "状态定义": definition}, tags=tuple(definition.get("标签") or ()))
            destination = frame.target
            definition["标签"] = sorted(frame.tags)
            failure = ""
            is_control = bool(definition.get("是否控制", False)) or "控制" in frame.tags
            immunities = self._immunities(destination)
            if frame.cancelled:
                failure = "被取消"
            elif "状态" in immunities or "负面状态" in immunities and definition.get("类别") == "负面":
                failure = "状态免疫"
            elif "控制" in immunities and is_control:
                failure = "控制免疫"
            if not failure and is_control:
                control_limit = int(destination.battle_profile.get("同时承受控制上限", 0))
                active_controls = sum(
                    1
                    for status in destination.statuses
                    if "控制" in status.tags or bool(status.action_limits)
                )
                if control_limit and active_controls >= control_limit:
                    failure = "控制承载已满"
            if not failure and is_control:
                base = float(definition.get("控制基础命中率", 100)) / 100.0
                chance = self._clamp(base + self._percent(source, "控制命中率") - self._percent(destination, "控制抵抗率"), 0.0, 1.0)
                if not self._judgement(context, "控制", chance):
                    failure = "控制抵抗"
            if failure:
                self._dispatch_event(context, kind="添加状态失败后", source=source, target=destination, values={"状态": str(definition.get("名称") or ""), "原因": failure}, tags=tuple(frame.tags))
                continue
            definition["来源"] = source.id
            definition["来源名称"] = source.name
            definition["来源能力"] = context.current_ability
            definition["构筑实例"] = self._build_instance(context, definition)
            definition["属性"] = {str(k): float(v) * multiplier for k, v in dict(definition.get("属性") or {}).items()}
            if is_control and str(definition.get("持续单位") or "状态承受者行动") != "整场战斗":
                duration = max(1, int(definition.get("剩余行动", 1)))
                duration = max(1, math.ceil(duration * (1.0 - self._clamp(self._percent(destination, "韧性"), 0.0, 0.9))))
                duration_limit = int(destination.battle_profile.get("控制持续上限", 0))
                definition["剩余行动"] = min(duration, duration_limit) if duration_limit else duration
            status = StatusState.from_dict(definition)
            allow_cross_build = bool(definition.get("允许跨构筑", False))
            existing = next(
                (
                    item
                    for item in destination.statuses
                    if item.name == status.name
                    and (
                        allow_cross_build
                        or not status.build_instance
                        or not item.build_instance
                        or status.build_instance == item.build_instance
                    )
                    and (
                        definition.get("叠加范围", "同名共享") == "同名共享"
                        or item.source == source.id
                    )
                ),
                None,
            )
            mode = str(definition.get("重复方式") or "刷新持续")
            if existing is None:
                destination.statuses.append(status)
                context.mark_listener_index_dirty()
            elif mode == "不叠加":
                continue
            elif mode == "增加层数":
                existing.stacks = min(existing.max_stacks, existing.stacks + status.stacks)
            elif mode == "增加层数并刷新":
                existing.stacks = min(existing.max_stacks, existing.stacks + status.stacks)
                existing.remaining_turns = max(existing.remaining_turns, status.remaining_turns)
            elif mode == "延长持续":
                existing.remaining_turns += status.remaining_turns
            else:
                existing.remaining_turns = max(existing.remaining_turns, status.remaining_turns)
            applied_status = status if existing is None else existing
            self._dispatch_event(
                context,
                kind="添加状态后",
                source=source,
                target=destination,
                values={
                    "状态": applied_status.name,
                    "状态类别": applied_status.category,
                    "状态层数": applied_status.stacks,
                    "剩余行动": applied_status.remaining_turns,
                    "持续单位": applied_status.duration_unit,
                    "来源名称": applied_status.source_name,
                },
                tags=applied_status.tags,
            )
            self._resolve_status_reactions(context, source, destination, status.name, multiplier)
            changed = True
        return changed

    def _resolve_status_reactions(self, context, source, target, added_name, multiplier):
        for reaction in self.catalog.status_reactions:
            required = [str(value) for value in reaction.get("需要状态") or ()]
            if added_name not in required:
                continue
            matched = []
            for name in required:
                status = next((value for value in target.statuses if value.name == name), None)
                if status is None:
                    break
                matched.append(status)
            else:
                consume = max(0, int(reaction.get("消耗层数", 1)))
                if any(status.stacks < consume for status in matched):
                    continue
                for status in matched:
                    status.stacks -= consume
                    if status.stacks <= 0 and status in target.statuses:
                        target.statuses.remove(status)
                        context.mark_listener_index_dirty()
                generated = reaction.get("生成状态")
                if isinstance(generated, Mapping):
                    value = copy.deepcopy(dict(generated))
                    value["来源"] = source.id
                    value["来源名称"] = source.name
                    value["来源能力"] = context.current_ability
                    value["构筑实例"] = self._build_instance(context, value)
                    target.statuses.append(StatusState.from_dict(value))
                    context.mark_listener_index_dirty()
                self._run_effects(context, source, target, reaction.get("效果") or (), multiplier)
                self._dispatch_event(
                    context,
                    kind="状态反应后",
                    source=source,
                    target=target,
                    values={
                        "反应": str(reaction.get("名称") or "状态反应"),
                        "消耗状态": required,
                        "生成状态": str((generated or {}).get("名称") or "") if isinstance(generated, Mapping) else "",
                    },
                )

    def _matching_statuses(self, context, fighter, selector):
        name = str(selector.get("名称") or "")
        category = str(selector.get("分类") or "")
        tags = {str(value) for value in selector.get("标签") or ()}
        allow_cross_build = bool(selector.get("允许跨构筑", False))
        current_instance = self._build_instance(context, selector)
        values = [
            status
            for status in fighter.statuses
            if (not name or status.name == name)
            and (not category or status.category == category)
            and (not tags or tags <= set(status.tags))
            and (
                allow_cross_build
                or not current_instance
                or not status.build_instance
                or status.build_instance == current_instance
            )
        ]
        order = str(selector.get("排序") or "获得顺序")
        if order == "层数从高到低":
            values.sort(key=lambda item: item.stacks, reverse=True)
        elif order == "剩余行动从少到多":
            values.sort(key=lambda item: item.remaining_turns)
        if not selector.get("选择全部", False):
            values = values[: max(1, int(selector.get("数量", 1)))]
        return values

    def _select_statuses(self, context, source, target, value):
        if not isinstance(value, Mapping):
            return []
        node = self.catalog.parse_node(value)
        if node.executor != "选择状态":
            raise ValueError("状态字段必须使用选择状态")
        result = []
        for fighter in self._select_targets(context, source, target, value.get("目标")):
            result.extend((fighter, status) for status in self._matching_statuses(context, fighter, value))
        return result

    def _ability_remove_status(self, context, source, target, effect, multiplier, **_):
        del multiplier
        pairs = self._select_statuses(context, source, target, effect.get("状态"))
        removed = False
        for owner, status in pairs:
            frame = self._dispatch_event(context, kind="移除状态前", source=source, target=owner, values={"状态": status.name, "状态层数": status.stacks}, tags=status.tags)
            if frame.cancelled:
                continue
            if status in owner.statuses:
                owner.statuses.remove(status)
                context.mark_listener_index_dirty()
                self._dispatch_event(context, kind="移除状态后", source=source, target=owner, values={"状态": status.name, "状态层数": status.stacks}, tags=status.tags)
                removed = True
        return removed

    def _ability_modify_status_stacks(self, context, source, target, effect, multiplier, consume=False, **_):
        pairs = self._select_statuses(context, source, target, effect.get("状态"))
        amount = max(0, int(float(effect.get("层数", effect.get("数值", 1))) * multiplier))
        if not pairs:
            return False
        for owner, status in pairs:
            before = status.stacks
            if consume or str(effect.get("方式") or "增加") == "减少":
                if before < amount and effect.get("不足时是否失败", True):
                    return False
                status.stacks = max(0, before - amount)
            else:
                status.stacks = min(status.max_stacks, before + amount)
            if status.stacks <= 0 and status in owner.statuses:
                owner.statuses.remove(status)
                context.mark_listener_index_dirty()
            self._dispatch_event(context, kind="状态层数变化后", source=source, target=owner, values={"状态": status.name, "变化前数值": before, "变化后数值": status.stacks})
        return True

    def _ability_modify_status_duration(self, context, source, target, effect, multiplier, **_):
        pairs = self._select_statuses(context, source, target, effect.get("状态"))
        amount = max(0, int(float(effect.get("持续数值", 1)) * multiplier))
        mode = str(effect.get("方式") or "增加")
        for _, status in pairs:
            status.remaining_turns = max(0, status.remaining_turns + (amount if mode == "增加" else -amount))
        return bool(pairs)

    def _ability_copy_status(self, context, source, target, effect, multiplier, **_):
        sources = self._select_statuses(context, source, target, effect.get("状态"))
        receivers = self._select_targets(context, source, target, effect.get("接收目标"))
        if not sources or not receivers:
            return False
        for _, status in sources:
            for receiver in receivers:
                copied = copy.deepcopy(status)
                frame = self._dispatch_event(
                    context,
                    kind="添加状态前",
                    source=source,
                    target=receiver,
                    values={"状态": copied.name, "状态定义": copied.to_dict()},
                    tags=(*copied.tags, "复制"),
                )
                if frame.cancelled:
                    continue
                receiver = frame.target
                copied.tags = tuple(frame.tags - {"复制"})
                receiver.statuses.append(copied)
                context.mark_listener_index_dirty()
                self._dispatch_event(
                    context,
                    kind="添加状态后",
                    source=source,
                    target=receiver,
                    values={
                        "状态": copied.name,
                        "状态类别": copied.category,
                        "状态层数": copied.stacks,
                        "剩余行动": copied.remaining_turns,
                        "持续单位": copied.duration_unit,
                        "来源名称": copied.source_name,
                    },
                    tags=copied.tags,
                )
        return True

    def _ability_transfer_status(self, context, source, target, effect, multiplier, **kwargs):
        pairs = self._select_statuses(context, source, target, effect.get("状态"))
        receivers = self._select_targets(context, source, target, effect.get("接收目标"))
        if not pairs or not receivers:
            return False
        for owner, status in pairs:
            owner.statuses.remove(status)
            receivers[0].statuses.append(status)
            context.mark_listener_index_dirty()
        return True

    def _ability_modify_action_progress(self, context, source, target, effect, multiplier, cost=False, **_):
        amount = max(0.0, float(effect.get("数值", 0)) * multiplier) / 100.0
        mode = str(effect.get("方式") or "增加")
        changed = False
        for destination in self._select_targets(context, source, target, effect.get("目标")):
            before = context.action_progress.get(destination.id, 0.0)
            if cost and before < amount:
                return False
            after = amount if mode == "设置" else before + amount if mode == "增加" else before - amount
            after = self._clamp(after, 0.0, 0.999999)
            context.action_progress[destination.id] = after
            self._dispatch_event(context, kind="行动条变化后", source=source, target=destination, amount=(after - before) * 100, values={"变化前数值": before * 100, "变化后数值": after * 100})
            changed = changed or before != after
        return changed

    def _ability_modify_cooldown(self, context, source, target, effect, multiplier, **_):
        mode = str(effect.get("方式") or "减少")
        amount = max(0, int(float(effect.get("数值", 0)) * multiplier))
        changed = False
        for fighter in self._select_targets(context, source, target, effect.get("目标")):
            for key in self._select_skills(context, fighter, effect.get("技能")):
                before = fighter.cooldowns.get(key, 0)
                after = amount if mode == "设置" else before + amount if mode == "增加" else 0 if mode == "清空" else max(0, before - amount)
                fighter.cooldowns[key] = after
                skill = self._skill_by_key(fighter, key)
                self._dispatch_event(context, kind="技能冷却变化后", source=source, target=fighter, amount=after - before, values={"技能": skill.name if skill else key, "技能键": key, "变化前数值": before, "变化后数值": after})
                if before > 0 and after == 0:
                    self._dispatch_event(context, kind="技能冷却完成后", source=source, target=fighter, values={"技能": skill.name if skill else key, "技能键": key})
                changed = changed or before != after
        return changed

    def _ability_modify_counter(self, context, source, target, effect, multiplier, **kwargs):
        name = str(effect.get("计量") or "")
        instance = self._build_instance(context, effect)
        mode = str(effect.get("方式") or "增加")
        amount = self._resolve_value(context, effect.get("数值", 0), source, target, kwargs.get("event_amount", 0), kwargs.get("event_values") or {}) * multiplier
        changed = False
        for fighter in self._select_targets(context, source, target, effect.get("目标")):
            key = (fighter.id, instance, name)
            before = context.ability_counters.get(key, float(effect.get("初始值", 0)))
            if mode == "减少" and before < amount and effect.get("不足时是否失败", True):
                return False
            after = amount if mode == "设置" else 0 if mode == "清空" else before + amount if mode == "增加" else before - amount
            after = self._clamp(after, float(effect.get("最低值", 0)), float(effect.get("最高值", 100)))
            context.ability_counters[key] = after
            changed = changed or before != after
        return changed

    @staticmethod
    def _build_instance(context, node: Mapping[str, Any] | None = None) -> str:
        """解析当前能力所属构筑实例；公共能力保持空作用域。"""

        value = (node or {}).get("构筑实例") if isinstance(node, Mapping) else None
        return str(value or context.current_build_instance or "").strip()

    def _ability_additional_attack(self, context, source, target, effect, multiplier, **_):
        destinations = self._select_targets(context, source, target, effect.get("目标"))
        if not destinations:
            return False
        cap = min(int(self.catalog.action_rules.get("每次主行动最多追加攻击", 3)), int(effect.get("每次主行动最多追加攻击", 3)))
        key = (source.id, "追加攻击")
        count = context.trigger_counts.get(key, 0)
        if count >= cap:
            return False
        context.trigger_counts[key] = count + 1
        destination = destinations[0]
        self._dispatch_event(context, kind="追加攻击前", source=source, target=destination, values={"行动类型": "追加攻击"}, tags=("追加攻击",))
        applied = self._deal_attack(context, source, destination, max(0.0, float(effect.get("威力倍率", 1)) * multiplier), str(effect.get("名称") or "追加攻击"), tags=("追加攻击", "派生伤害"), allow_followups=False)
        self._dispatch_event(context, kind="追加攻击后", source=source, target=destination, amount=applied, values={"实际数值": applied, "行动类型": "追加攻击"}, tags=("追加攻击",))
        return True

    def _ability_share_damage(self, context, source, target, effect, multiplier, **_):
        frame = self._current_event(context, "造成伤害前")
        destinations = self._select_targets(context, source, target, effect.get("目标"))
        if not destinations:
            return False
        amount = max(0.0, frame.amount * float(effect.get("比例", 0)) / 100.0 * multiplier)
        frame.facts["当前数值"] = max(0.0, frame.amount - amount)
        self._apply_damage(context, frame.source, destinations[0], amount, label=str(effect.get("名称") or "分摊伤害"), damage_form="分摊", defense_rule="真实", can_critical=False, can_block=False, tags=("分摊",))
        return True

    def _ability_transfer_damage(self, context, source, target, effect, multiplier, **kwargs):
        frame = self._current_event(context)
        if frame.kind not in {"造成伤害前", "受到致命伤害"}:
            raise ValueError("转移伤害只能修改伤害前或致命伤害事件")
        destinations = self._select_targets(context, source, target, effect.get("目标"))
        if not destinations:
            return False
        amount = min(frame.amount, max(0.0, self._resolve_value(context, effect.get("数值"), source, target, kwargs.get("event_amount", 0), kwargs.get("event_values") or {}) * multiplier))
        remaining_damage = max(0.0, frame.amount - amount)
        if frame.kind == "受到致命伤害":
            frame.cancelled = True
            retained_health = max(1.0, frame.target.health - remaining_damage)
            frame.facts["保留血气"] = max(
                retained_health,
                float(frame.facts.get("保留血气", 0)),
            )
        else:
            frame.facts["当前数值"] = remaining_damage
        self._apply_damage(context, frame.source, destinations[0], amount, label=str(effect.get("名称") or "转移伤害"), damage_form="转移", defense_rule="真实", can_critical=False, can_block=False, tags=("转移",))
        return True

    def _ability_fatal_guard(self, context, source, target, effect, multiplier, **_):
        frame = self._current_event(context, "受到致命伤害")
        amount = max(1.0, float(effect.get("保留血气", 1)) * multiplier)
        frame.facts["保留血气"] = max(float(frame.facts.get("保留血气", 0)), amount)
        frame.cancelled = True
        return True

    def _ability_revive(self, context, source, target, effect, multiplier, **_):
        changed = False
        for fighter in self._select_targets(context, source, target, effect.get("目标")):
            if fighter.alive:
                continue
            fighter.active = True
            fighter.health = max(1.0, fighter.health_max * float(effect.get("血气百分比", 10)) / 100.0 * multiplier)
            fighter.spirit = fighter.spirit_max * float(effect.get("精神百分比", 0)) / 100.0
            self._dispatch_event(context, kind="复活后", source=source, target=fighter, amount=fighter.health, values={"实际数值": fighter.health})
            changed = True
        return changed

    def _ability_modify_event_value(self, context, source, target, effect, multiplier, **kwargs):
        frame = self._current_event(context)
        self._require_event_mutation(frame, "当前数值")
        amount = self._resolve_value(context, effect.get("数值"), source, target, kwargs.get("event_amount", frame.amount), frame.facts) * multiplier
        mode = str(effect.get("方式") or "设置")
        frame.facts["当前数值"] = max(0.0, amount if mode == "设置" else frame.amount + amount if mode == "增加" else frame.amount - amount if mode == "减少" else frame.amount * amount / 100.0)
        return True

    def _ability_modify_event_target(self, context, source, target, effect, multiplier, **_):
        del multiplier
        frame = self._current_event(context)
        self._require_event_mutation(frame, "目标")
        values = self._select_targets(context, source, target, effect.get("目标"))
        if not values:
            return False
        frame.target = values[0]
        frame.facts["承受者"] = values[0].id
        return True

    def _ability_modify_event_tags(self, context, source, target, effect, multiplier, **_):
        del source, target, multiplier
        frame = self._current_event(context)
        self._require_event_mutation(frame, "标签")
        values = {str(value) for value in effect.get("标签") or ()}
        mode = str(effect.get("方式") or "添加")
        frame.tags = values if mode == "设置" else frame.tags - values if mode == "移除" else frame.tags | values
        frame.facts["标签"] = sorted(frame.tags)
        return True

    def _ability_cancel_event(self, context, source, target, effect, multiplier, **_):
        del source, target, effect, multiplier
        frame = self._current_event(context)
        self._require_event_mutation(frame, "取消")
        frame.cancelled = True
        frame.facts["已取消"] = True
        return True

    def _ability_trigger_skill(self, context, source, target, effect, multiplier, **_):
        limit = int(self.catalog.action_rules.get("触发技能嵌套上限", self.MAX_TRIGGERED_SKILLS))
        if context.triggered_skill_depth >= limit:
            return False
        selected = self._select_skills(context, source, effect.get("技能"))
        if not selected:
            return False
        destinations = self._select_targets(context, source, target, effect.get("目标")) or [target]
        context.triggered_skill_depth += 1
        try:
            return self._cast_skill(
                context,
                source,
                destinations[0],
                self._skill_by_key(source, selected[0]),
                triggered=True,
                ignore_cost=bool(effect.get("忽略代价", False)),
                ignore_cooldown=bool(effect.get("忽略冷却", False)),
                multiplier=multiplier,
            )
        finally:
            context.triggered_skill_depth -= 1

    def _ability_record_fact(self, context, source, target, effect, multiplier, **kwargs):
        owners = (
            self._select_targets(context, source, target, effect.get("归属"))
            if effect.get("归属") is not None
            else [source]
        )
        name = str(effect.get("名称") or "")
        value = self._resolve_any(context, effect.get("值"), source, target, kwargs.get("event_amount", 0), kwargs.get("event_values") or {})
        mode = str(effect.get("方式") or "追加")
        limit = max(1, int(effect.get("保留数量", 1)))
        for owner in owners:
            key = (owner.id, name)
            values = context.records.setdefault(key, [])
            if mode == "清空":
                values.clear()
            elif mode == "覆盖":
                values[:] = [copy.deepcopy(value)]
            elif mode == "累加":
                values[:] = [float(values[-1] if values else 0) + float(value) * multiplier]
            else:
                values.append(copy.deepcopy(value))
                del values[:-limit]
        return True

    def _ability_modify_relation(self, context, source, target, effect, multiplier, **_):
        del multiplier
        left = self._select_targets(context, source, target, effect.get("一方")) or [source]
        right = self._select_targets(context, source, target, effect.get("另一方")) or [target]
        name = str(effect.get("名称") or "关联")
        mode = str(effect.get("方式") or "建立")
        before = len(context.relations)
        if mode == "解除":
            context.relations[:] = [item for item in context.relations if not (item["名称"] == name and {item["一方"], item["另一方"]} == {left[0].id, right[0].id})]
        else:
            context.relations.append({"名称": name, "一方": left[0].id, "另一方": right[0].id, "标签": list(effect.get("标签") or ()), "记录": copy.deepcopy(dict(effect.get("记录") or {}))})
        self._dispatch_event(context, kind="关联变化后", source=source, target=right[0], values={"关联": name, "方式": mode})
        return before != len(context.relations)

    def _ability_modify_skill(self, context, source, target, effect, multiplier, **_):
        changed = False
        for fighter in self._select_targets(context, source, target, effect.get("目标")):
            for key in self._select_skills(context, fighter, effect.get("技能")):
                skill = self._skill_by_key(fighter, key)
                if skill is None:
                    continue
                field = str(effect.get("字段") or "")
                mode = str(effect.get("方式") or "设置")
                value = effect.get("值")
                attr = {"名称": "name", "精神消耗": "spirit_cost", "冷却行动": "cooldown_actions", "释放顺序": "release_order", "威力倍率": "multiplier", "禁用": "disabled", "目标标签": "tags", "效果": "effects"}.get(field)
                if attr is None:
                    raise ValueError(f"技能字段不能修改：{field}")
                before = getattr(skill, attr)
                if isinstance(before, (int, float)) and not isinstance(before, bool):
                    numeric = float(value) * multiplier
                    after = numeric if mode == "设置" else before + numeric if mode == "增加" else before - numeric
                    if isinstance(before, int):
                        after = int(after)
                elif attr in {"tags", "effects"}:
                    values = tuple(copy.deepcopy(value or ()))
                    after = values if mode == "设置" else (*before, *values)
                else:
                    after = bool(value) if attr == "disabled" else str(value)
                setattr(skill, attr, after)
                self._dispatch_event(context, kind="技能变化后", source=source, target=fighter, values={"技能": skill.name, "技能键": key, "字段": field, "变化前数值": before, "变化后数值": after})
                changed = True
        return changed

    def _ability_copy_skill(self, context, source, target, effect, multiplier, **_):
        sources = self._select_targets(context, source, target, effect.get("来源目标"))
        receivers = self._select_targets(context, source, target, effect.get("接收目标"))
        if not sources or not receivers:
            return False
        keys = self._select_skills(context, sources[0], effect.get("技能"))
        if not keys:
            return False
        original = self._skill_by_key(sources[0], keys[0])
        receiver = receivers[0]
        copied = original.clone(key=f"复制:{receiver.id}:{len(receiver.skills)}:{original.key}", name=str(effect.get("名称") or original.name))
        copied.multiplier *= multiplier
        receiver.skills.append(copied)
        return True

    def _ability_modify_intent(self, context, source, target, effect, multiplier, **_):
        del multiplier
        intent = context.action_intent
        if intent is None:
            return False
        field = str(effect.get("字段") or "目标")
        if field == "取消":
            intent.cancelled = True
        elif field == "行动":
            intent.action = str(effect.get("值") or "普通攻击")
        elif field == "目标":
            values = self._select_targets(context, source, target, effect.get("目标"))
            if not values:
                return False
            intent.target_id = values[0].id
        elif field == "技能":
            skills = self._select_skills(context, source, effect.get("技能"))
            if not skills:
                return False
            intent.skill_key = skills[0]
            intent.action = "技能"
        else:
            raise ValueError(f"未知行动意图字段：{field}")
        if context.event_stack and context.event_stack[-1].kind == "行动决策前":
            frame = context.event_stack[-1]
            frame.cancelled = intent.cancelled
            frame.facts.update({"行动类型": intent.action, "技能键": intent.skill_key, "目标ID": intent.target_id})
            selected_target = context.fighter_by_id(intent.target_id)
            if selected_target is not None:
                frame.target = selected_target
        self._dispatch_event(context, kind="行动意图变化后", source=source, target=target, values={"字段": field, "行动": intent.action, "技能键": intent.skill_key, "目标ID": intent.target_id})
        return True

    def _ability_transform_event(self, context, source, target, effect, multiplier, **_):
        del multiplier
        frame = self._current_event(context)
        self._require_event_mutation(frame, "类型")
        destination = str(effect.get("事件") or "")
        self.catalog.require_event(destination)
        resource_gain_events = {"恢复前", "获得护盾前", "资源恢复前"}
        if frame.kind not in resource_gain_events or destination not in resource_gain_events:
            raise ValueError(f"事件 {frame.kind} 不能转化为 {destination}：两者没有共同结算语义")
        frame.transformed_kind = destination
        self._dispatch_event(context, kind="事件转化后", source=source, target=target, values={"原事件": frame.kind, "新事件": destination})
        return True

    def _ability_modify_judgement(self, context, source, target, effect, multiplier, **_):
        del source, target, multiplier
        kind = str(effect.get("判定") or "任意")
        context.judgement_overrides.setdefault(kind, []).append({"方式": str(effect.get("方式") or "必定成功"), "次数": max(1, int(effect.get("次数", 1)))})
        return True

    def _ability_modify_battle_rule(self, context, source, target, effect, multiplier, **_):
        del target, multiplier
        name = str(effect.get("名称") or "")
        mode = str(effect.get("方式") or "添加")
        if mode == "移除":
            before = len(context.battle_rules)
            context.battle_rules[:] = [rule for rule in context.battle_rules if str(rule.get("名称") or "") != name]
            changed = before != len(context.battle_rules)
            if changed:
                context.mark_listener_index_dirty()
        else:
            duplicate_mode = str(effect.get("重复处理") or "允许")
            existing = [
                rule for rule in context.battle_rules
                if str(rule.get("名称") or "") == name
            ]
            if existing and duplicate_mode in {"拒绝", "已存在则拒绝"}:
                return False
            definition = copy.deepcopy(dict(effect.get("规则") or {}))
            unknown = set(definition) - {"监听"}
            if unknown:
                raise ValueError("战场规则存在无执行语义字段：" + "、".join(sorted(unknown)))
            context.battle_rules.append({
                **definition,
                "名称": name,
                "来源": source.id,
                "来源退场时移除": bool(effect.get("来源退场时移除", False)),
            })
            context.mark_listener_index_dirty()
            changed = True
        self._dispatch_event(context, kind="战场规则变化后", source=source, target=source, values={"规则": name, "方式": mode})
        return changed

    def _ability_save_result(self, context, source, target, effect, multiplier, **kwargs):
        name = str(effect.get("名称") or "")
        source_name = str(effect.get("来源") or "上个效果")
        value = context.last_result if source_name == "上个效果" else self._resolve_any(context, effect.get("值"), source, target, kwargs.get("event_amount", 0), kwargs.get("event_values") or {})
        context.saved_results[name] = copy.deepcopy(value)
        return True

    def _ability_switch_form(self, context, source, target, effect, multiplier, **_):
        changed = False
        for fighter in self._select_targets(context, source, target, effect.get("目标")):
            name = str(effect.get("形态") or "")
            definition = dict(effect.get("定义") or fighter.forms.get(name) or {})
            if not name or fighter.form == name:
                continue
            before = fighter.form
            for key, value in fighter.form_modifiers.items():
                fighter.attributes[key] = fighter.attributes.get(key, 0.0) - value
            fighter.form_modifiers = {
                str(key): float(value) * multiplier
                for key, value in dict(definition.get("属性变化") or {}).items()
            }
            for key, value in fighter.form_modifiers.items():
                fighter.attributes[key] = fighter.attributes.get(key, 0.0) + value
            if fighter.base_form_skills is None:
                fighter.base_form_skills = copy.deepcopy(fighter.skills)
            if definition.get("替换技能"):
                fighter.skills = [self._skill_from_definition(fighter, index, value) for index, value in enumerate(definition["替换技能"])]
            else:
                fighter.skills = copy.deepcopy(fighter.base_form_skills)
            if not definition.get("保留冷却", True):
                fighter.cooldowns.clear()
            fighter.form = name
            self._dispatch_event(context, kind="形态切换后", source=source, target=fighter, values={"原形态": before, "形态": name})
            changed = True
        return changed

    def _ability_create_object(self, context, source, target, effect, multiplier, **_):
        definition = copy.deepcopy(dict(effect.get("定义") or {}))
        kind = str(effect.get("类型") or "构造物")
        side = source.side if str(effect.get("阵营") or "己方") == "己方" else 1 - source.side
        if kind == "参战者":
            if sum(value.summoned and value.side == side and value.active for value in context.fighters) >= int(self.catalog.action_rules.get("每方召唤物上限", 6)):
                return False
        elif len(context.combat_objects) >= int(self.catalog.action_rules.get("战斗构造物上限", 12)):
            return False
        next_serial = context.summon_serial + 1
        object_id = str(definition.get("编号") or f"{source.id}:战斗对象:{next_serial}")
        if context.fighter_by_id(object_id) is not None or object_id in context.combat_objects:
            return False
        context.summon_serial = next_serial
        name = str(definition.get("名称") or kind)
        if kind == "参战者":
            attributes = {str(k): float(v) * multiplier for k, v in dict(definition.get("属性") or {}).items()}
            fighter = Fighter(
                id=object_id,
                name=name,
                attributes=attributes,
                health=max(1.0, float(attributes.get("血气上限", 1))),
                spirit=max(0.0, float(attributes.get("精神上限", 0))),
                skills=[self._skill_from_definition(source, index, value, prefix=object_id) for index, value in enumerate(definition.get("技能") or ())],
                passives=[{"监听键": f"{object_id}:{i}", "结算顺序": i, "节点": copy.deepcopy(value)} for i, value in enumerate(definition.get("被动") or ())],
                combatant_type=str(definition.get("身份") or "召唤物"),
                side=side,
                owner_id=source.id,
                controller_id=source.controller_id or source.id,
                summoned=True,
                tags={str(value) for value in definition.get("标签") or ()},
            )
            context.add_fighter(fighter)
            event_target = fighter
        else:
            obj = CombatObject(object_id, name, kind, side, source.id, int(definition.get("持续行动", 0)), float(definition.get("耐久", 0)), list(copy.deepcopy(definition.get("监听") or ())), copy.deepcopy(dict(definition.get("记录") or {})), {str(value) for value in definition.get("标签") or ()})
            context.combat_objects[object_id] = obj
            context.mark_listener_index_dirty()
            durability = max(1.0, obj.health or 1.0)
            fighter = Fighter(
                id=object_id,
                name=name,
                attributes={"血气上限": durability, "精神上限": 0, "护盾上限": 0, "攻击": 0, "防御": float(definition.get("防御", 0)), "速度": 1},
                health=durability,
                spirit=0,
                combatant_type="构造物",
                side=side,
                owner_id=source.id,
                controller_id=source.id,
                tags=set(obj.tags),
                can_act=False,
                counts_for_victory=False,
            )
            context.add_fighter(fighter)
            event_target = fighter
        self._dispatch_event(context, kind="战斗对象入场后", source=source, target=event_target, values={"对象ID": object_id, "对象类型": kind, "名称": name})
        return True

    def _ability_remove_object(self, context, source, target, effect, multiplier, **_):
        del multiplier
        object_id = str(effect.get("对象ID") or "")
        candidates = [fighter for fighter in context.fighters if fighter.active and fighter.summoned and (fighter.id == object_id or (not object_id and fighter.owner_id == source.id))]
        for fighter in candidates:
            self._retire_battle_object(context, source, fighter, "参战者")
        objects = [obj for obj in context.combat_objects.values() if obj.id == object_id or (not object_id and obj.owner_id == source.id)]
        for obj in objects:
            shell = context.fighter_by_id(obj.id)
            self._retire_battle_object(context, source, shell or target, obj.object_type, object_id=obj.id)
        return bool(candidates or objects)

    def _retire_battle_object(self, context, source, fighter, kind, *, object_id=""):
        combat_object_id = object_id or fighter.id
        obj = context.combat_objects.pop(combat_object_id, None)
        if obj is not None:
            obj.active = False
            context.mark_listener_index_dirty()
        if not fighter.active and obj is None:
            return False
        fighter.active = False
        fighter.health = 0
        self._dispatch_event(
            context,
            kind="战斗对象退场后",
            source=source,
            target=fighter,
            values={"对象ID": combat_object_id, "对象类型": kind},
        )
        self._remove_source_lifetimes(context, fighter)
        return True

    def _remove_source_lifetimes(self, context, source):
        for fighter in context.fighters:
            expired = [status for status in fighter.statuses if status.expire_with_source and status.source == source.id]
            for status in expired:
                fighter.statuses.remove(status)
                context.mark_listener_index_dirty()
                self._dispatch_event(
                    context,
                    kind="移除状态后",
                    source=source,
                    target=fighter,
                    values={"状态": status.name, "状态层数": status.stacks, "原因": "来源退场"},
                    tags=status.tags,
                )
        removed_rules = [
            rule for rule in context.battle_rules
            if str(rule.get("来源") or "") == source.id and rule.get("来源退场时移除", False)
        ]
        if removed_rules:
            context.battle_rules[:] = [rule for rule in context.battle_rules if rule not in removed_rules]
            context.mark_listener_index_dirty()
            for rule in removed_rules:
                self._dispatch_event(
                    context,
                    kind="战场规则变化后",
                    source=source,
                    target=source,
                    values={"规则": str(rule.get("名称") or ""), "方式": "来源退场移除"},
                )

    def _ability_modify_ownership(self, context, source, target, effect, multiplier, **_):
        del multiplier
        values = self._select_targets(context, source, target, effect.get("目标"))
        if not values:
            return False
        destination = values[0]
        field = str(effect.get("字段") or "阵营")
        if field == "阵营":
            new_side = source.side if str(effect.get("阵营") or "己方") == "己方" else 1 - source.side
            if destination.side != new_side:
                old_team = context.left_team if destination.side == 0 else context.right_team
                new_team = context.left_team if new_side == 0 else context.right_team
                old_team.remove(destination)
                new_team.append(destination)
                destination.side = new_side
                context.rebuild_indexes()
                if destination.id in context.combat_objects:
                    context.combat_objects[destination.id].side = new_side
        elif field == "主人":
            owners = self._select_targets(context, source, target, effect.get("归属目标"))
            if not owners:
                return False
            destination.owner_id = owners[0].id
            if destination.id in context.combat_objects:
                context.combat_objects[destination.id].owner_id = owners[0].id
        elif field == "控制者":
            controllers = self._select_targets(context, source, target, effect.get("归属目标"))
            if not controllers:
                return False
            destination.controller_id = controllers[0].id
        else:
            raise ValueError(f"未知归属字段：{field}")
        return True

    def _ability_replay_effect(self, context, source, target, effect, multiplier, **kwargs):
        scope = str(effect.get("范围") or "上个效果")
        history = [item for item in context.effect_history if item.get("成功")]
        if scope == "自身上个效果":
            history = [item for item in history if item.get("来源") == source.id]
        if not history:
            return False
        item = copy.deepcopy(history[-1])
        destinations = self._select_targets(context, source, target, effect.get("目标")) or [target]
        return self._execute_mechanism(context, source, destinations[0], item["节点"], float(item.get("倍率", 1)) * float(effect.get("倍率", 1)) * multiplier, **kwargs)

    def _ability_modify_tactic(self, context, source, target, effect, multiplier, **_):
        del multiplier
        changed = False
        for fighter in self._select_targets(context, source, target, effect.get("目标")):
            mode = str(effect.get("方式") or "替换")
            rules = copy.deepcopy(list(effect.get("战术") or ()))
            fighter.tactic = rules if mode == "替换" else [*fighter.tactic, *rules] if mode == "追加" else []
            changed = True
        return changed

    def _select_skills(self, context, fighter, value):
        if not isinstance(value, Mapping):
            return []
        node = self.catalog.parse_node(value)
        if node.executor != "选择技能":
            raise ValueError("技能字段必须使用选择技能")
        return self._skills_select(context, fighter, fighter, value, 0, {}, ())

    def _skills_select(self, context, source, target, selector, *_):
        del target
        scope = str(selector.get("范围") or "全部技能")
        candidates = [skill for skill in source.skills if (scope != "冷却中的技能" or source.cooldowns.get(skill.key, 0) > 0) and (scope != "可用技能" or self._skill_available(source, skill))]
        if scope == "当前技能":
            candidates = [skill for skill in candidates if skill.key == source.current_skill]
        if scope == "指定技能":
            name = str(selector.get("名称") or "")
            candidates = [skill for skill in candidates if skill.key == name or skill.name == name]
        order = str(selector.get("排序") or "无")
        if order == "随机":
            candidates = list(candidates)
            context.rng.shuffle(candidates)
        elif order == "冷却从高到低":
            candidates.sort(key=lambda skill: source.cooldowns.get(skill.key, 0), reverse=True)
        elif order == "冷却从低到高":
            candidates.sort(key=lambda skill: source.cooldowns.get(skill.key, 0))
        elif order == "释放顺序":
            candidates.sort(key=self._skill_order_key)
        count = len(candidates) if selector.get("选择全部", False) else max(1, int(selector.get("数量", 1)))
        return [skill.key for skill in candidates[:count]]

    def _resolve_value(self, context, value, source, target, event_amount=0.0, event_values=None):
        result = self._resolve_any(context, value, source, target, event_amount, event_values or {})
        if isinstance(result, bool) or not isinstance(result, (int, float)):
            raise TypeError(f"战斗数值必须是数字：{result!r}")
        return float(result)

    def _resolve_any(self, context, value, source, target, event_amount=0.0, event_values=None):
        if isinstance(value, Mapping):
            if "能力" not in value:
                return copy.deepcopy(dict(value))
            node = self.catalog.parse_node(value)
            handler = self._value_handlers.get(node.executor)
            if handler is None:
                raise ValueError(f"战斗核心未实现数值执行器：{node.executor or '<空>'}")
            return handler(context, source, target, dict(value), event_amount, event_values or {})
        return value if value is not None else 0

    def _value_read(self, context, source, target, node, event_amount, event_values):
        origin = str(node.get("来源") or "固定值")
        destinations = self._select_targets(context, source, target, node.get("目标")) or [target]
        selected = destinations[0]
        if origin == "固定值":
            value: Any = node.get("固定值", 0)
        elif origin in {"自身属性", "效果来源属性"}:
            value = source.value(str(node.get("属性") or ""))
        elif origin == "目标属性":
            value = selected.value(str(node.get("属性") or ""))
        elif origin == "事件事实":
            value = event_values.get(str(node.get("事实") or ""), 0)
        elif origin == "本次数值":
            value = event_amount
        elif origin == "保存结果":
            value = context.saved_results.get(str(node.get("名称") or ""), 0)
            field = str(node.get("字段") or "")
            if field and isinstance(value, Mapping):
                value = value.get(field, 0)
        elif origin == "战斗记录":
            values = context.records.get((selected.id, str(node.get("名称") or "")), [])
            value = values[-1] if values else 0
        elif origin == "构筑计量":
            value = context.ability_counters.get(
                (
                    selected.id,
                    self._build_instance(context, node),
                    str(node.get("计量") or ""),
                ),
                0,
            )
        elif origin == "状态层数":
            value = sum(status.stacks for status in selected.statuses if status.name == str(node.get("状态") or ""))
        elif origin == "行动条":
            value = context.action_progress.get(selected.id, 0) * 100
        elif origin == "技能冷却":
            value = sum(selected.cooldowns.get(key, 0) for key in self._select_skills(context, selected, node.get("技能")))
        elif origin.startswith("目标当前"):
            resource = origin.removeprefix("目标当前")
            value = self._resource_values(selected, resource)[0]
        elif origin.startswith("自身当前"):
            resource = origin.removeprefix("自身当前")
            value = self._resource_values(source, resource)[0]
        elif origin.startswith("目标已损失"):
            current, maximum = self._resource_values(selected, origin.removeprefix("目标已损失"))
            value = maximum - current
        elif origin.startswith("自身已损失"):
            current, maximum = self._resource_values(source, origin.removeprefix("自身已损失"))
            value = maximum - current
        else:
            value = event_values.get(origin, 0)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = float(value) * float(node.get("百分比", 100)) / 100.0
            if "最低值" in node:
                value = max(float(node["最低值"]), value)
            if "最高值" in node:
                value = min(float(node["最高值"]), value)
        return value

    def _value_calculate(self, context, source, target, node, amount, values):
        left = self._resolve_value(context, node.get("左值"), source, target, amount, values)
        right = self._resolve_value(context, node.get("右值"), source, target, amount, values)
        mode = str(node.get("方式") or "相加")
        result = {"相加": left + right, "相减": left - right, "相乘": left * right, "取小": min(left, right), "取大": max(left, right)}.get(mode)
        if mode == "相除":
            result = 0.0 if right == 0 else left / right
        elif mode == "取余":
            result = 0.0 if right == 0 else left % right
        elif mode == "乘方":
            result = left**right
        if result is None:
            raise ValueError(f"未知数值计算方式：{mode}")
        result = self._clamp(result, float(node.get("最低值", -math.inf)), float(node.get("最高值", math.inf)))
        return round(result, max(0, int(node.get("保留小数位", 4))))

    def _value_random(self, context, source, target, node, *_):
        del source, target
        low, high = float(node.get("最低值", 0)), float(node.get("最高值", 0))
        value = context.rng.uniform(low, high)
        return round(value) if node.get("取整", False) else value

    def _value_aggregate(self, context, source, target, node, amount, values):
        targets = self._select_targets(context, source, target, node.get("目标"))
        mode = str(node.get("方式") or "数量")
        if mode == "数量":
            return float(len(targets))
        data = [self._resolve_value(context, node.get("数值"), source, fighter, amount, values) for fighter in targets]
        if not data:
            return 0.0
        return {"总和": sum(data), "最小": min(data), "最大": max(data), "平均": sum(data) / len(data), "不同值数量": float(len(set(data)))}.get(mode, 0.0)

    def _select_targets(self, context, source, target, value):
        if value is None:
            return [target]
        if not isinstance(value, Mapping):
            raise TypeError("目标字段必须使用选择目标")
        node = self.catalog.parse_node(value)
        if node.executor != "选择目标":
            raise ValueError("目标字段必须使用选择目标")
        return self._target_select(context, source, target, dict(value), 0, {}, ())

    def _target_select(self, context, source, target, selector, *_):
        scope = str(selector.get("范围") or "当前目标")
        frame = context.event_stack[-1] if context.event_stack else None
        if scope == "自身":
            candidates = [source]
        elif scope == "当前目标":
            candidates = [target]
        elif scope == "效果来源":
            candidates = [source]
        elif scope == "事件来源":
            candidates = [frame.source] if frame else []
        elif scope == "事件承受者":
            candidates = [frame.target] if frame else []
        elif scope == "行动者":
            actor = context.fighter_by_id(str(frame.facts.get("行动者") or "")) if frame else None
            candidates = [actor] if actor else []
        elif scope == "己方":
            candidates = context.allies_of(source, alive=None)
        elif scope == "敌方":
            candidates = context.enemies_of(source, alive=None)
        elif scope in {"全体", "任意"}:
            candidates = list(context.fighters)
        elif scope == "关联对象":
            name = str(selector.get("关联") or "")
            ids = [item["另一方"] if item["一方"] == source.id else item["一方"] for item in context.relations if item["名称"] == name and source.id in {item["一方"], item["另一方"]}]
            candidates = [fighter for value in ids if (fighter := context.fighter_by_id(value))]
        elif scope == "主人":
            owner = context.fighter_by_id(source.owner_id)
            candidates = [owner] if owner else []
        elif scope == "控制者":
            owner = context.fighter_by_id(source.controller_id)
            candidates = [owner] if owner else []
        elif scope == "本编组主战者":
            candidates = [
                value
                for value in context.allies_of(source, alive=None)
                if source.group_id
                and value.group_id == source.group_id
                and value.group_role == "主战者"
            ]
            candidates.sort(
                key=lambda value: (
                    value.alive,
                    value.value("攻击"),
                    value.value("血气上限"),
                    value.value("防御"),
                    -context.fighter_order.get(value.id, 0),
                ),
                reverse=True,
            )
        else:
            raise ValueError(f"未知目标范围：{scope}")
        candidates = [value for value in candidates if value is not None]
        life = str(selector.get("生存状态") or "存活")
        if life == "存活":
            candidates = [value for value in candidates if value.alive]
        elif life == "死亡":
            candidates = [value for value in candidates if not value.alive]
        if selector.get("排除自身", False):
            candidates = [value for value in candidates if value is not source]
        combatant_type = str(selector.get("身份") or "")
        if combatant_type:
            candidates = [value for value in candidates if value.combatant_type == combatant_type or combatant_type in value.tags]
        object_type = str(selector.get("对象类型") or "参战者")
        if object_type == "参战者":
            candidates = [value for value in candidates if value.combatant_type != "构造物"]
        elif object_type == "召唤物":
            candidates = [value for value in candidates if value.summoned]
        elif object_type == "构造物":
            candidates = [value for value in candidates if value.combatant_type == "构造物"]
        elif object_type != "任意":
            raise ValueError(f"未知战斗对象类型：{object_type}")
        status_name = str(selector.get("拥有状态") or "")
        if status_name:
            candidates = [value for value in candidates if any(status.name == status_name for status in value.statuses)]
        order = str(selector.get("排序") or "默认")
        if order == "随机":
            candidates = list(candidates)
            context.rng.shuffle(candidates)
        elif order == "血气比例从低到高":
            candidates.sort(key=lambda value: value.health / value.health_max)
        elif order == "血气比例从高到低":
            candidates.sort(key=lambda value: value.health / value.health_max, reverse=True)
        elif order == "速度从高到低":
            candidates.sort(key=lambda value: value.value("速度", 100), reverse=True)
        elif order == "行动条从高到低":
            candidates.sort(key=lambda value: context.action_progress.get(value.id, 0), reverse=True)
        count = len(candidates) if selector.get("选择全部", False) else max(1, int(selector.get("数量", 1)))
        return candidates[:count]

    @staticmethod
    def _resource_values(target, resource):
        if resource == "血气":
            return target.health, target.health_max
        if resource == "精神":
            return target.spirit, target.spirit_max
        if resource == "护盾":
            return target.shield, target.shield_max
        raise ValueError(f"战斗核心未登记资源：{resource}")

    @staticmethod
    def _set_resource(target, resource, value):
        if resource == "血气":
            target.health = value
        elif resource == "精神":
            target.spirit = value
        elif resource == "护盾":
            target.shield = value
        else:
            raise ValueError(f"战斗核心未登记资源：{resource}")

    @staticmethod
    def _immunities(fighter):
        return {value for status in fighter.statuses for value in status.effect_immunities}

    def _current_event(self, context, expected: str | None = None):
        if not context.event_stack:
            raise ValueError("当前没有可以修改的战斗事件")
        frame = context.event_stack[-1]
        if expected and frame.kind != expected:
            raise ValueError(f"当前事件不是{expected}")
        return frame

    def _require_event_mutation(self, frame, field):
        contract = self.catalog.require_event(frame.kind)
        if field not in set(contract.get("可修改") or ()):
            raise ValueError(f"事件 {frame.kind} 不允许修改{field}")

    def _judgement(self, context, kind, chance, roll=None):
        overrides = context.judgement_overrides.get(kind) or context.judgement_overrides.get("任意") or []
        if overrides:
            value = overrides[0]
            mode = value["方式"]
            value["次数"] -= 1
            if value["次数"] <= 0:
                overrides.pop(0)
            if mode == "必定成功":
                return True
            if mode == "必定失败":
                return False
            if mode == "反转":
                actual = context.rng.random() if roll is None else roll
                return not (actual < self._clamp(chance, 0, 1))
            if mode == "重掷取优":
                actual = context.rng.random() if roll is None else roll
                return min(actual, context.rng.random()) < self._clamp(chance, 0, 1)
        actual = context.rng.random() if roll is None else roll
        return actual < self._clamp(chance, 0, 1)

    @staticmethod
    def _skill_by_key(fighter, key):
        return next((skill for skill in fighter.skills if skill.key == key), None)

    @staticmethod
    def _skill_available(fighter, skill):
        return not skill.disabled and (not skill.use_limit or skill.uses < skill.use_limit) and fighter.cooldowns.get(skill.key, 0) <= 0

    def _skill_order_key(self, skill):
        values = {
            "释放顺序": int(skill.release_order),
            "来源层级升序": self._source_layer(skill.source_category),
            "装配位序": int(skill.born_order),
            "物品编号": str(skill.source_id),
            "能力序号": int(skill.ability_order),
        }
        order = self.catalog.timing["主动技能"]["排序"]
        return tuple(values[field] for field in order) + (str(skill.key),)

    @staticmethod
    def _skill_from_definition(owner, index, definition, prefix=""):
        value = dict(definition)
        source_id = str(value.get("编号") or prefix or owner.id)
        return Skill(
            key=str(value.get("编号") or f"{prefix or owner.id}:技能:{index}"),
            name=str(value.get("名称") or f"技能{index + 1}"),
            born_order=index,
            release_order=int(value.get("释放顺序", index + 1)),
            source_id=source_id,
            build_instance=str(value.get("实例") or prefix or ""),
            ability_order=index,
            multiplier=float(value.get("威力倍率", 1)),
            spirit_cost=max(0.0, float(value.get("精神消耗", 0))),
            cooldown_actions=max(0, int(value.get("冷却行动", 0))),
            effects=tuple(copy.deepcopy(value.get("效果") or ())),
            tags=tuple(str(item) for item in value.get("标签") or ()),
            costs=tuple(copy.deepcopy(value.get("额外代价") or ())),
        )

    @staticmethod
    def _clamp(value, minimum, maximum):
        return min(float(maximum), max(float(minimum), float(value)))
