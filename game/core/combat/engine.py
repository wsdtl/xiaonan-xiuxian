"""行动条与技能 CD 驱动的 JSON 战斗核心。"""

from __future__ import annotations


import copy
import math
import random
from collections.abc import Callable, Mapping
from typing import Any

from .contracts import (
    CombatantResult,
    CombatFieldResult,
    CombatFormationResult,
    CombatResult,
    StatusResult,
)
from .damage import DamageEngine, DamageRequest
from .mechanics import AbilityRuntime
from .models import (
    ActionIntent,
    BattleContext,
    CombatCatalog,
    Fighter,
    PreparedCombatField,
    PreparedFormation,
    RuntimeCombatantSnapshot,
    RuntimeCombatField,
    RuntimeFormation,
    Skill,
    StatusState,
)


class BattleEngine(AbilityRuntime):
    """执行自动战斗；所有内容规则均来自传入的 JSON 目录。"""

    def __init__(self, combat_rules: Mapping[str, Any] | None = None) -> None:
        rules = dict(combat_rules or {})
        # 构筑模板库由 `template_data.py` 生成，经基石字典传进来；不参与 JSON 校验。
        templates = rules.pop("构筑模板库", None)
        self.catalog = CombatCatalog.from_mapping(rules, templates)
        self.damage = DamageEngine(self.catalog.damage_rules, self.catalog.attributes)
        self._ability_handlers: dict[str, Callable[..., bool]] = {
            "顺序执行": self._ability_sequence,
            "条件执行": self._ability_conditional,
            "随机执行": self._ability_random,
            "遍历目标": self._ability_iterate,
            "重复执行": self._ability_repeat,
            "尝试执行": self._ability_attempt,
            "事务执行": self._ability_transaction,
            "监听事件": self._ability_listener,
            "造成伤害": self._ability_damage,
            "恢复资源": self._ability_recover_resource,
            "消耗资源": self._ability_consume_resource,
            "支付代价": self._ability_pay_cost,
            "设置资源": self._ability_set_resource,
            "转移资源": self._ability_transfer_resource,
            "添加状态": self._ability_add_status,
            "移除状态": self._ability_remove_status,
            "修改状态层数": self._ability_modify_status_stacks,
            "修改状态持续": self._ability_modify_status_duration,
            "复制状态": self._ability_copy_status,
            "转移状态": self._ability_transfer_status,
            "修改行动条": self._ability_modify_action_progress,
            "修改技能冷却": self._ability_modify_cooldown,
            "修改构筑计量": self._ability_modify_counter,
            "追加攻击": self._ability_additional_attack,
            "分摊伤害": self._ability_share_damage,
            "转移伤害": self._ability_transfer_damage,
            "抵挡致命伤害": self._ability_fatal_guard,
            "复活": self._ability_revive,
            "修改事件数值": self._ability_modify_event_value,
            "修改事件目标": self._ability_modify_event_target,
            "修改事件标签": self._ability_modify_event_tags,
            "取消事件": self._ability_cancel_event,
            "触发技能": self._ability_trigger_skill,
            "记录战斗事实": self._ability_record_fact,
            "修改战斗关联": self._ability_modify_relation,
            "修改技能": self._ability_modify_skill,
            "复制技能": self._ability_copy_skill,
            "修改行动意图": self._ability_modify_intent,
            "转化事件": self._ability_transform_event,
            "修改判定": self._ability_modify_judgement,
            "修改战场规则": self._ability_modify_battle_rule,
            "保存结果": self._ability_save_result,
            "切换形态": self._ability_switch_form,
            "创建战斗对象": self._ability_create_object,
            "移除战斗对象": self._ability_remove_object,
            "修改归属": self._ability_modify_ownership,
            "回放效果": self._ability_replay_effect,
            "修改战术": self._ability_modify_tactic,
        }
        self._condition_handlers = {
            "概率条件": self._condition_probability,
            "数值条件": self._condition_numeric,
            "状态条件": self._condition_status,
            "类型条件": self._condition_type,
            "组合条件": self._condition_combined,
            "标签条件": self._condition_tags,
        }
        self._value_handlers = {
            "读取数值": self._value_read,
            "计算数值": self._value_calculate,
            "随机数值": self._value_random,
            "聚合数值": self._value_aggregate,
        }
        self._target_handlers = {"选择目标": self._target_select}
        self._skill_selector_handlers = {"选择技能": self._skills_select}
        self._assembly_handlers = {
            "装配属性": self._assemble_attributes,
            "装配主动技能": self._assemble_active_skill,
            "装配被动技能": self._assemble_passive_skill,
        }

    def simulate(
        self,
        *,
        left,
        right,
        medicine_definitions,
        medicine_selection_strategy,
        seed,
        action_limit,
    ) -> CombatResult:
        return self.simulate_teams(
            left=(left,),
            right=(right,),
            medicine_definitions=medicine_definitions,
            medicine_selection_strategy=medicine_selection_strategy,
            seed=seed,
            action_limit=action_limit,
        )

    def simulate_teams(
        self,
        *,
        left: tuple[RuntimeCombatantSnapshot, ...],
        right: tuple[RuntimeCombatantSnapshot, ...],
        medicine_definitions: dict[str, Any],
        medicine_selection_strategy: str,
        seed: int,
        action_limit: int,
        field: PreparedCombatField | None = None,
        formations: tuple[PreparedFormation, ...] = (),
    ) -> CombatResult:
        if not left or not right:
            raise ValueError("战斗双方都必须至少有一名参战者")
        ids = [str(value.id).strip() for value in (*left, *right)]
        if any(not value for value in ids) or len(ids) != len(set(ids)):
            raise ValueError("参战者 ID 必须非空且不可重复")
        left_fighters = [self._build_fighter(value) for value in left]
        right_fighters = [self._build_fighter(value) for value in right]
        # 归属转换可能把原始队伍清空；保留开始时的首位对象用于摘要字段。
        left_anchor = left_fighters[0]
        right_anchor = right_fighters[0]
        self._share_inventories(left_fighters)
        self._share_inventories(right_fighters)
        runtime_field = self._build_field(field, (*left_fighters, *right_fighters))
        runtime_formations = [self._build_formation(value) for value in formations]
        context = BattleContext(
            rng=random.Random(int(seed)),
            left=left_fighters[0],
            right=right_fighters[0],
            medicine_definitions=medicine_definitions,
            medicine_selection_strategy=medicine_selection_strategy,
            field=runtime_field,
            left_team=left_fighters,
            right_team=right_fighters,
            formations=runtime_formations,
        )
        context.engine = self
        context.action_progress = {fighter.id: 0.0 for fighter in context.fighters}
        if context.field is not None:
            self._form_field(context)
        self._form_formations(context)
        context.event(
            "战斗开始",
            context.left,
            context.right,
            f"{'、'.join(value.name for value in left_fighters)}与{'、'.join(value.name for value in right_fighters)}进入战斗",
            values={
                "左方": [value.id for value in left_fighters],
                "右方": [value.id for value in right_fighters],
            },
        )
        while context.both_sides_alive and context.action_number < max(
            1, int(action_limit)
        ):
            order = self._next_action_order(context)
            for actor in order:
                if not actor.alive or not context.both_sides_alive:
                    continue
                context.action_number += 1
                context.trigger_counts.clear()
                context.saved_results.clear()
                self._take_action(context, actor)
                if context.action_number >= max(1, int(action_limit)):
                    break
        left_alive = [
            value
            for value in context.left_team
            if value.alive and value.counts_for_victory
        ]
        right_alive = [
            value
            for value in context.right_team
            if value.alive and value.counts_for_victory
        ]
        draw = bool(left_alive) == bool(right_alive)
        context.event(
            "战斗结束",
            context.left,
            context.right,
            "战斗未分胜负"
            if draw
            else f"{'、'.join(value.name for value in left_alive or right_alive)}取胜",
            values={
                "结果": "未分胜负" if draw else "分出胜负",
                "行动数": context.action_number,
            },
        )
        left_results = tuple(self._fighter_result(value) for value in context.left_team)
        right_results = tuple(
            self._fighter_result(value) for value in context.right_team
        )
        return CombatResult(
            # 归属转换可能让一方队伍为空；摘要字段保留原始首位，
            # 队伍字段仍如实反映战斗结束时的实际阵营。
            left=left_results[0] if left_results else self._fighter_result(left_anchor),
            right=right_results[0] if right_results else self._fighter_result(right_anchor),
            actions=context.action_number,
            events=tuple(context.events),
            trigger_activations=sum(context.battle_trigger_counts.values()),
            left_team=left_results,
            right_team=right_results,
            field=self._field_result(context),
            formations=tuple(
                self._formation_result(value) for value in context.formations
            ),
        )

    @staticmethod
    def _share_inventories(fighters: list[Fighter]) -> None:
        groups: dict[str, list[Fighter]] = {}
        for fighter in fighters:
            if fighter.inventory_owner_id:
                groups.setdefault(fighter.inventory_owner_id, []).append(fighter)
        for owner_id, members in groups.items():
            declared = [dict(member.inventory) for member in members if member.inventory]
            if declared and any(value != declared[0] for value in declared[1:]):
                raise ValueError(f"同一库存归属提交了不同库存快照：{owner_id}")
            shared = declared[0] if declared else {}
            for member in members:
                member.inventory = shared

    def _formation_base_cycle(self) -> int:
        """阵法轮转的**基准周期**，来自 `时序.json -> 阵法轮转.基准周期`。

        这个数原先写死在这里（`math.ceil(12 * …)`）。它是负载节奏的数——各品级靠
        `传导` 缩放它，黄/玄/地/天分别是 1.0/1.45/2.1/3.05，于是首轮落在
        第 12/9/6/4 行动——所以它和 `伤害.json` 的那几个闸是同一类东西，放数据里。
        """

        section = self.catalog.timing.get("阵法轮转") or {}
        return max(1, int(section.get("基准周期", 12)))

    def _build_formation(self, definition: PreparedFormation) -> RuntimeFormation:
        stage = definition.stages[0]
        interval = max(
            1,
            math.ceil(
                self._formation_base_cycle()
                * stage.cycle_multiplier
                / max(1.0, definition.transmission)
            ),
        )
        return RuntimeFormation(definition, definition.capacity, interval)

    def _form_formations(self, context: BattleContext) -> None:
        for formation in sorted(
            context.formations,
            key=lambda value: (
                value.definition.side,
                value.definition.position,
                value.definition.formation_id,
            ),
        ):
            context.event(
                "阵法展开",
                context.left if formation.side == 0 else context.right,
                context.right if formation.side == 0 else context.left,
                f"{formation.definition.name}以{formation.definition.grade}品展开",
                values={
                    "阵法编号": formation.definition.formation_id,
                    "阵法名称": formation.definition.name,
                    "品级": formation.definition.grade,
                    "方位": formation.definition.position,
                    "阵基承载": formation.definition.capacity,
                    "阵眼冲击": formation.definition.impact,
                    "节点数量": formation.definition.nodes,
                },
            )

    @staticmethod
    def _formation_result(value: RuntimeFormation) -> CombatFormationResult:
        return CombatFormationResult(
            formation_id=value.definition.formation_id,
            name=value.definition.name,
            grade=value.definition.grade,
            side=value.definition.side,
            position=value.definition.position,
            capacity=round(value.definition.capacity, 3),
            remaining_capacity=round(max(0.0, value.remaining_capacity), 3),
            impact=round(value.definition.impact, 3),
            nodes=value.definition.nodes,
            rotations=value.rotations,
            collapsed=value.collapsed,
        )

    @staticmethod
    def _build_field(
        definition: PreparedCombatField | None,
        fighters: tuple[Fighter, ...],
    ) -> RuntimeCombatField | None:
        if definition is None:
            return None
        health_basis = sum(
            fighter.health_max
            for fighter in fighters
            if fighter.counts_for_victory
            and not fighter.summoned
            and fighter.combatant_type != "构造物"
        )
        source = Fighter(
            id=f"战场环境:{definition.environment_id}",
            name=definition.name,
            attributes={
                "血气上限": 1,
                "精神上限": 0,
                "护盾上限": 0,
                "攻击": 0,
                "防御": 0,
                "速度": 1,
            },
            health=1,
            spirit=0,
            combatant_type="战场环境",
            side=-1,
            can_act=False,
            counts_for_victory=False,
        )
        return RuntimeCombatField(
            definition=definition,
            source=source,
            health_basis=max(1.0, health_basis),
        )

    def _form_field(self, context: BattleContext) -> None:
        field = context.field
        if field is None:
            return
        context.mark_listener_index_dirty()
        self._run_effects(
            context,
            field.source,
            context.left,
            field.stage.entry_abilities,
            1.0,
        )
        definition = field.definition
        context.event(
            "战场形成",
            field.source,
            context.left,
            f"{definition.name}形成，当前地势为{field.stage.name}",
            values={
                "环境编号": definition.environment_id,
                "环境": definition.name,
                "阶段": field.stage.name,
                "承载基准": field.health_basis,
                "场景": definition.scene,
            },
        )

    def _absorb_field_damage(
        self,
        context: BattleContext,
        source: Fighter,
        target: Fighter,
        amount: float,
    ) -> None:
        field = context.field
        if field is None or source.combatant_type == "战场环境" or amount <= 0:
            return
        field.accumulated_damage += float(amount)
        context.event(
            "地势承伤后",
            field.source,
            target,
            f"{field.definition.name}承受战斗余波 {amount:.3f}",
            amount,
            values={
                "环境编号": field.definition.environment_id,
                "阶段": field.stage.name,
                "本次承伤": amount,
                "累计承伤": field.accumulated_damage,
                "承载基准": field.health_basis,
                "承伤比例": field.damage_ratio,
            },
        )
        while field.stage_index + 1 < len(field.definition.stages):
            next_stage = field.definition.stages[field.stage_index + 1]
            if field.damage_ratio < next_stage.threshold:
                break
            previous = field.stage
            context.event(
                "地势变化前",
                field.source,
                target,
                f"{field.definition.name}将由{previous.name}转为{next_stage.name}",
                values={
                    "环境编号": field.definition.environment_id,
                    "原阶段": previous.name,
                    "新阶段": next_stage.name,
                    "累计承伤": field.accumulated_damage,
                    "承伤比例": field.damage_ratio,
                },
            )
            field.stage_index += 1
            context.mark_listener_index_dirty()
            self._run_effects(
                context,
                field.source,
                target,
                field.stage.entry_abilities,
                1.0,
            )
            context.event(
                "地势变化后",
                field.source,
                target,
                f"{field.definition.name}进入{field.stage.name}",
                values={
                    "环境编号": field.definition.environment_id,
                    "原阶段": previous.name,
                    "新阶段": field.stage.name,
                    "累计承伤": field.accumulated_damage,
                    "承伤比例": field.damage_ratio,
                },
            )

    @staticmethod
    def _field_result(context: BattleContext) -> CombatFieldResult | None:
        field = context.field
        if field is None:
            return None
        definition = field.definition
        return CombatFieldResult(
            environment_id=definition.environment_id,
            name=definition.name,
            scene=definition.scene,
            origin=definition.origin,
            xy=definition.xy,
            altitude=definition.altitude,
            terrain=definition.terrain,
            stage_index=field.stage_index,
            stage_name=field.stage.name,
            accumulated_damage=round(field.accumulated_damage, 3),
            health_basis=round(field.health_basis, 3),
        )

    def _take_action(self, context: BattleContext, actor: Fighter) -> None:
        target = context.opponent_of(actor)
        context.event(
            "行动开始",
            actor,
            actor,
            f"{actor.name}开始行动",
            values={"行动": context.action_number, "行动者": actor.id},
        )
        self._recover_at_action_start(context, actor)
        self._tick_cooldowns(context, actor)
        if not self._action_restricted(actor, "使用丹药"):
            self._use_medicine(context, actor)
        intent = self._decide_action(context, actor, target)
        context.action_intent = intent
        planned_target = context.fighter_by_id(intent.target_id) or target
        decision = context.event(
            "行动决策前",
            actor,
            planned_target,
            f"{actor.name}准备行动",
            values={
                "行动者": actor.id,
                "行动类型": intent.action,
                "技能键": intent.skill_key,
                "目标ID": intent.target_id,
            },
        )
        if decision is not None:
            intent.cancelled = intent.cancelled or decision.cancelled
            intent.target_id = decision.target.id
        context.event(
            "行动决策后",
            actor,
            decision.target if decision is not None else planned_target,
            f"{actor.name}确定行动",
            values={
                "行动者": actor.id,
                "行动类型": intent.action,
                "技能键": intent.skill_key,
                "目标ID": intent.target_id,
            },
        )
        actual_target = context.fighter_by_id(intent.target_id) or target
        if intent.cancelled or self._action_restricted(actor, "行动"):
            context.event(
                "行动跳过后",
                actor,
                actor,
                f"{actor.name}未能行动",
                values={"行动者": actor.id, "行动类型": intent.action},
            )
        elif intent.action == "技能":
            skill = self._skill_by_key(actor, intent.skill_key)
            uses_before = skill.uses if skill is not None else 0
            succeeded = self._cast_skill(context, actor, actual_target, skill)
            if skill is not None and skill.uses > uses_before:
                self._advance_skill_cursor(actor, skill)
            if not succeeded:
                self._basic_attack(context, actor, actual_target)
        else:
            self._basic_attack(context, actor, actual_target)
        context.action_intent = None
        self._advance_lifecycles(context, actor)
        context.event(
            "行动结束",
            actor,
            actual_target,
            f"{actor.name}结束行动",
            values={"行动": context.action_number, "行动者": actor.id},
        )
        self._rotate_formations(context)

    def _rotate_formations(self, context: BattleContext) -> None:
        """到期的阵法各轮转一次：定目标、摊算冲击、结算、播报。"""

        active = [value for value in context.formations if value.active]
        due = [
            value for value in active if context.action_number >= value.next_rotation
        ]
        if not due:
            return
        node_rules = self.catalog.formation_rules
        prepared = self._prepare_rotations(context, active, due, node_rules)
        formation_damage, fighter_damage, impact_events = (
            self._aggregate_rotation_impacts(context, prepared, node_rules)
        )
        collapsed, formation_absorbed, health_changes = self._apply_rotation_damage(
            context, active, formation_damage, fighter_damage
        )
        self._announce_rotation_impacts(
            context, active, impact_events, formation_absorbed, health_changes
        )
        self._announce_formation_collapses(context, collapsed)

    def _prepare_rotations(
        self,
        context: BattleContext,
        active: list[RuntimeFormation],
        due: list[RuntimeFormation],
        node_rules: Any,
    ) -> list[tuple[RuntimeFormation, float, tuple[Fighter | RuntimeFormation, ...]]]:
        """给每个到期阵法定下本轮的冲击强度与目标，并播报轮转。

        `next_rotation` 与 `rotations` 在**选目标之前**就推进：没有目标的阵法同样
        算轮转过一次，只是不播报、不结算。这是原有语义，别把次序调过来。
        """

        stage_index = context.field.stage_index if context.field is not None else 0
        prepared: list[
            tuple[RuntimeFormation, float, tuple[Fighter | RuntimeFormation, ...]]
        ] = []
        for formation in sorted(
            due,
            key=lambda value: (
                value.definition.side,
                value.definition.position,
                value.definition.formation_id,
            ),
        ):
            stage = formation.definition.stages[
                min(stage_index, len(formation.definition.stages) - 1)
            ]
            interval = max(
                1,
                math.ceil(
                    self._formation_base_cycle()
                    * stage.cycle_multiplier
                    / max(1.0, formation.definition.transmission)
                ),
            )
            formation.next_rotation = context.action_number + interval
            formation.rotations += 1
            impact = formation.definition.impact * stage.impact_multiplier
            targets = self._rotation_targets(context, formation, active, node_rules)
            if targets is None:
                continue
            prepared.append((formation, impact, targets))
            context.event(
                "阵法轮转后",
                context.left if formation.side == 0 else context.right,
                context.right if formation.side == 0 else context.left,
                f"{formation.definition.name}完成第{formation.rotations}次轮转",
                values={
                    "阵法编号": formation.definition.formation_id,
                    "阵法名称": formation.definition.name,
                    "方位": formation.definition.position,
                    "轮转次数": formation.rotations,
                    "阵势倍率": stage.impact_multiplier,
                    "行动周期倍率": stage.cycle_multiplier,
                },
            )
        return prepared

    def _rotation_targets(
        self,
        context: BattleContext,
        formation: RuntimeFormation,
        active: list[RuntimeFormation],
        node_rules: Any,
    ) -> tuple[Fighter | RuntimeFormation, ...] | None:
        """本轮冲击谁：按规则先打敌方阵法，否则打存活修士。`None` 表示无目标。"""

        enemy_formations = [
            value
            for value in active
            if value.side != formation.side and value.active
        ]
        if node_rules.enemy_formation_first and enemy_formations:
            return (
                min(
                    enemy_formations,
                    key=lambda value: (
                        value.definition.position,
                        value.definition.formation_id,
                    ),
                ),
            )
        enemies = context.right_team if formation.side == 0 else context.left_team
        alive = [
            value for value in enemies if value.alive and value.counts_for_victory
        ]
        if not alive:
            return None
        minimum = node_rules.minimum_targets
        count_field = node_rules.target_count_field
        available_count = {
            "节点": formation.definition.nodes,
        }[count_field]
        target_count = min(len(alive), max(minimum, available_count))
        return tuple(alive[:target_count])

    def _aggregate_rotation_impacts(
        self,
        context: BattleContext,
        prepared: list[
            tuple[RuntimeFormation, float, tuple[Fighter | RuntimeFormation, ...]]
        ],
        node_rules: Any,
    ) -> tuple[
        dict[int, float],
        dict[str, float],
        list[tuple[Fighter, Fighter, float, Mapping[str, Any]]],
    ]:
        """把各阵法的冲击摊到具体阵基与修士身上，并攒下待播报的冲击事件。"""

        formation_damage: dict[int, float] = {}
        fighter_damage: dict[str, float] = {}
        impact_events: list[tuple[Fighter, Fighter, float, Mapping[str, Any]]] = []
        for formation, impact, targets in prepared:
            split_impact = (
                impact / len(targets)
                if node_rules.impact_distribution == "均分"
                else impact
            )
            for target in targets:
                if isinstance(target, RuntimeFormation):
                    formation_damage[id(target)] = (
                        formation_damage.get(id(target), 0.0) + split_impact
                    )
                else:
                    fighter_damage[target.id] = (
                        fighter_damage.get(target.id, 0.0) + split_impact
                    )
                source = context.left if formation.side == 0 else context.right
                target_fighter = (
                    context.left
                    if isinstance(target, RuntimeFormation) and target.side == 0
                    else context.right
                    if isinstance(target, RuntimeFormation)
                    else target
                )
                impact_events.append(
                    (
                        source,
                        target_fighter,
                        split_impact,
                        {
                            "阵法编号": formation.definition.formation_id,
                            "阵法名称": formation.definition.name,
                            "方位": formation.definition.position,
                            "冲击目标": target.definition.formation_id
                            if isinstance(target, RuntimeFormation)
                            else target.id,
                            "覆盖目标数": len(targets),
                            "冲击数值": split_impact,
                            "是否命中阵法": isinstance(target, RuntimeFormation),
                        },
                    )
                )
        return formation_damage, fighter_damage, impact_events

    def _apply_rotation_damage(
        self,
        context: BattleContext,
        active: list[RuntimeFormation],
        formation_damage: dict[int, float],
        fighter_damage: dict[str, float],
    ) -> tuple[
        list[RuntimeFormation], dict[int, float], dict[str, tuple[float, float]]
    ]:
        """先扣阵基承载力（归零即崩解），再扣修士血气并处理因此阵亡的挂钩。

        返回（崩解清单、阵基实收、各修士血气前后）：播报阶段要用实收值，
        不能用名义冲击值。
        """

        collapsed: list[RuntimeFormation] = []
        formation_absorbed: dict[int, float] = {}
        for formation in active:
            damage = formation_damage.get(id(formation), 0.0)
            if damage <= 0:
                continue
            formation_absorbed[id(formation)] = min(
                formation.remaining_capacity, damage
            )
            formation.remaining_capacity = max(
                0.0, formation.remaining_capacity - damage
            )
            if formation.remaining_capacity <= 0 and not formation.collapsed:
                formation.collapsed = True
                collapsed.append(formation)
        fighter_health_changes: dict[str, tuple[float, float]] = {}
        for fighter in context.fighters:
            damage = fighter_damage.get(fighter.id, 0.0)
            if damage > 0 and fighter.alive:
                health_before = fighter.health
                was_alive = fighter.alive
                fighter.health = max(0.0, fighter.health - damage)
                fighter_health_changes[fighter.id] = (
                    health_before,
                    fighter.health,
                )
                if was_alive and not fighter.alive:
                    fighter.spirit = 0
                    source = context.left if fighter.side == 1 else context.right
                    values = {"实际数值": damage, "伤害形式": "阵法冲击"}
                    self._dispatch_event(
                        context,
                        kind="死亡后",
                        source=source,
                        target=fighter,
                        amount=damage,
                        values=values,
                        tags=("阵法", "宏观冲击"),
                    )
                    self._dispatch_event(
                        context,
                        kind="击杀后",
                        source=source,
                        target=fighter,
                        amount=damage,
                        values=values,
                        tags=("阵法", "宏观冲击"),
                    )
                    self._remove_source_lifetimes(context, fighter)
        return collapsed, formation_absorbed, fighter_health_changes

    def _announce_rotation_impacts(
        self,
        context: BattleContext,
        active: list[RuntimeFormation],
        impact_events: list[tuple[Fighter, Fighter, float, Mapping[str, Any]]],
        formation_absorbed: dict[int, float],
        fighter_health_changes: dict[str, tuple[float, float]],
    ) -> None:
        """播报每次冲击：数值取**实际**发生的那一份（阵基实收或血气差）。"""

        for source, target, impact, values in impact_events:
            event_values = dict(values)
            if bool(event_values["是否命中阵法"]):
                target_formation = next(
                    (
                        value
                        for value in active
                        if value.definition.formation_id == event_values["冲击目标"]
                    ),
                    None,
                )
                event_values["实际数值"] = (
                    formation_absorbed.get(id(target_formation), impact)
                    if target_formation is not None
                    else impact
                )
            else:
                health_before, health_after = fighter_health_changes.get(
                    target.id, (target.health, target.health)
                )
                event_values.update(
                    {
                        "实际数值": health_before - health_after,
                        "伤害前血气": health_before,
                        "伤害后血气": health_after,
                    }
                )
            context.event(
                "阵法冲击后",
                source,
                target,
                f"{event_values['阵法名称']}完成宏观冲击",
                impact,
                values=event_values,
                tags=("阵法", "宏观冲击"),
            )

    def _announce_formation_collapses(
        self, context: BattleContext, collapsed: list[RuntimeFormation]
    ) -> None:
        """播报阵基崩解。"""

        for formation in collapsed:
            context.event(
                "阵法崩解后",
                context.left if formation.side == 0 else context.right,
                context.right if formation.side == 0 else context.left,
                f"{formation.definition.name}阵基崩解",
                values={
                    "阵法编号": formation.definition.formation_id,
                    "阵法名称": formation.definition.name,
                    "方位": formation.definition.position,
                    "原因": "阵基承载归零",
                    "累计轮转": formation.rotations,
                },
            )

    def _decide_action(self, context, actor, default_target) -> ActionIntent:
        for rule in sorted(
            actor.tactic, key=lambda value: int(value.get("优先级", 0)), reverse=True
        ):
            if not self._conditions_allow(
                context, actor, default_target, rule.get("条件") or (), 0, {}, ()
            ):
                continue
            targets = self._select_targets(
                context, actor, default_target, rule.get("目标")
            ) or [default_target]
            skills = self._select_skills(context, actor, rule.get("技能"))
            action = str(rule.get("行动") or ("技能" if skills else "普通攻击"))
            return ActionIntent(
                actor.id, action, targets[0].id, skills[0] if skills else ""
            )
        skill = self._next_skill_from_cursor(actor)
        fallback = str(self.catalog.action_rules["主动技能轮转"]["游标"]["无可用行动"])
        return ActionIntent(
            actor.id,
            "技能" if skill else fallback,
            default_target.id,
            skill.key if skill else "",
        )

    def _next_skill_from_cursor(self, actor: Fighter) -> Skill | None:
        if not actor.skills:
            return None
        start = actor.skill_cursor % len(actor.skills)
        for offset in range(len(actor.skills)):
            skill = actor.skills[(start + offset) % len(actor.skills)]
            if self._skill_available(
                actor, skill
            ) and actor.spirit >= self._skill_spirit_cost(actor, skill):
                return skill
        return None

    def _advance_skill_cursor(self, actor: Fighter, skill: Skill) -> None:
        if not actor.skills:
            actor.skill_cursor = 0
            return
        index = next(
            (
                index
                for index, candidate in enumerate(actor.skills)
                if candidate.key == skill.key
            ),
            None,
        )
        if index is not None:
            offset = int(
                self.catalog.action_rules["主动技能轮转"]["游标"]["成功后偏移"]
            )
            actor.skill_cursor = (index + offset) % len(actor.skills)

    def _build_fighter(self, snapshot: RuntimeCombatantSnapshot) -> Fighter:
        attributes = self._normalize_attributes(snapshot.attributes)
        attributes["攻击"] = attributes.get("攻击", 0) + float(snapshot.weapon_attack)
        skills, passives = self._technique_rules(list(snapshot.techniques), attributes)
        attributes = self._normalize_attributes(attributes)
        health_max = max(1.0, attributes.get("血气上限", 1))
        spirit_max = max(0.0, attributes.get("精神上限", 0))
        return Fighter(
            id=str(snapshot.id),
            name=str(snapshot.name or "无名参战者"),
            attributes=attributes,
            health=self._clamp(
                health_max if snapshot.health is None else snapshot.health,
                0,
                health_max,
            ),
            spirit=self._clamp(
                spirit_max if snapshot.spirit is None else snapshot.spirit,
                0,
                spirit_max,
            ),
            shield=self._clamp(
                snapshot.shield, 0, max(0.0, attributes.get("护盾上限", 0))
            ),
            statuses=[StatusState.from_dict(value) for value in snapshot.statuses],
            skills=list(skills),
            passives=list(passives),
            cooldowns={str(k): max(0, int(v)) for k, v in snapshot.cooldowns.items()},
            inventory={str(k): max(0, int(v)) for k, v in snapshot.inventory.items()},
            inventory_owner_id=str(snapshot.inventory_owner_id),
            auto_medicine=snapshot.auto_medicine,
            medicine_threshold=self._clamp(snapshot.medicine_threshold, 0, 1),
            skill_cursor=max(0, int(snapshot.skill_cursor)),
            level=max(1, int(snapshot.level)),
            combatant_type=str(snapshot.combatant_type or "修士"),
            gender=str(snapshot.gender or ""),
            owner_id=str(snapshot.owner_id),
            controller_id=str(snapshot.controller_id or snapshot.id),
            group_id=str(snapshot.group_id),
            group_role=str(snapshot.group_role or "主战者"),
            form=str(snapshot.form or "本相"),
            forms=copy.deepcopy(dict(snapshot.forms)),
            tags=set(snapshot.tags),
            tactic=copy.deepcopy(list(snapshot.tactic)),
            battle_profile=self._normalize_battle_profile(snapshot.battle_profile),
            five_elements=self._normalize_five_elements(snapshot.five_elements),
        )

    @staticmethod
    def _fighter_result(fighter: Fighter) -> CombatantResult:
        return CombatantResult(
            id=fighter.id,
            name=fighter.name,
            attributes=dict(fighter.attributes),
            level=fighter.level,
            combatant_type=fighter.combatant_type,
            health=max(0.0, round(fighter.health, 3)),
            spirit=max(0.0, round(fighter.spirit, 3)),
            shield=max(0.0, round(fighter.shield, 3)),
            statuses=tuple(
                BattleEngine._status_result(status)
                for status in fighter.statuses
                if status.remaining_turns > 0 and status.duration_unit != "整场战斗"
            ),
            cooldowns={k: v for k, v in fighter.cooldowns.items() if v > 0},
            inventory={k: v for k, v in fighter.inventory.items() if v > 0},
            consumed_items=dict(fighter.consumed_items),
            inventory_owner_id=fighter.inventory_owner_id,
            skill_cursor=fighter.skill_cursor,
            form=fighter.form,
            owner_id=fighter.owner_id,
            controller_id=fighter.controller_id,
            group_id=fighter.group_id,
            group_role=fighter.group_role,
            counts_for_victory=fighter.counts_for_victory,
            five_elements=dict(fighter.five_elements),
        )

    @staticmethod
    def _normalize_five_elements(value):
        allowed = {"木", "火", "土", "金", "水"}
        result = {str(key): float(amount) for key, amount in dict(value or {}).items()}
        if set(result) != allowed:
            raise ValueError("参战者五行根性必须完整包含木火土金水")
        if any(amount < 0 or amount > 100 for amount in result.values()):
            raise ValueError("参战者五行根性必须在 0 到 100 之间")
        if abs(sum(result.values()) - 100) > 1e-6:
            raise ValueError("参战者五行根性总和必须为 100")
        return result

    @staticmethod
    def _status_result(status: StatusState) -> StatusResult:
        return StatusResult(
            name=status.name,
            category=status.category,
            remaining_turns=status.remaining_turns,
            source=status.source,
            source_name=status.source_name,
            source_ability=status.source_ability,
            build_instance=status.build_instance,
            modifiers=dict(status.modifiers),
            stacks=status.stacks,
            max_stacks=status.max_stacks,
            tags=tuple(status.tags),
            duration_unit=status.duration_unit,
            action_limits=tuple(status.action_limits),
            effect_immunities=tuple(status.effect_immunities),
            listeners=tuple(copy.deepcopy(status.listeners)),
            values=copy.deepcopy(status.values),
            expire_with_source=status.expire_with_source,
        )

    def _next_action_order(self, context):
        while True:
            values = self._action_window(context)
            if values:
                return values

    def _action_window(self, context):
        ready = []
        for fighter in context.fighters:
            if not fighter.alive or not fighter.can_act:
                continue
            efficiency = self._action_efficiency(context, fighter)
            before = context.action_progress.get(fighter.id, 0)
            total = before + efficiency
            count = math.floor(total + 1e-9)
            context.action_progress[fighter.id] = min(max(total - count, 0), 1 - 1e-12)
            for ordinal in range(count):
                ready.append(
                    (
                        (ordinal + 1 - before) / efficiency,
                        -fighter.value("速度", 100),
                        fighter.side,
                        ordinal,
                        context.fighter_order.get(fighter.id, 0),
                        fighter,
                    )
                )
        ready.sort(key=lambda value: value[:-1])
        return tuple(value[-1] for value in ready)

    def _action_efficiency(self, context, fighter):
        rules = self.catalog.action_rules
        baseline = max(0.0001, float(rules.get("标准速度", 100)))
        minimum = max(0.0001, float(rules.get("最低有效速度", 25)))
        global_limit = max(1.000001, float(rules.get("最高行动效率", 2)))
        limit = max(
            1.000001, float(fighter.battle_profile.get("行动效率上限", global_limit))
        )
        effective = max(minimum, fighter.value("速度", 100))
        efficiency = limit * effective / (effective + (limit - 1) * baseline)

        response = dict(fighter.battle_profile.get("寡敌应变") or {})
        extra_enemies = max(0, len(context.enemies_of(fighter)) - 1)
        response_per_enemy = max(0.0, float(response.get("每名额外敌人行动效率", 0)))
        response_limit = max(0.0, float(response.get("行动效率增量上限", 0)))
        response_bonus = min(extra_enemies * response_per_enemy, response_limit)
        return min(limit, efficiency + response_bonus)

    @staticmethod
    def _normalize_battle_profile(value):
        profile = copy.deepcopy(dict(value or {}))
        allowed = {"行动效率上限", "寡敌应变", "同时承受控制上限", "控制持续上限"}
        unknown = set(profile) - allowed
        if unknown:
            raise ValueError(
                "战斗规格存在未知字段："
                + "、".join(sorted(str(item) for item in unknown))
            )
        if "行动效率上限" in profile:
            limit = profile["行动效率上限"]
            if (
                isinstance(limit, bool)
                or not isinstance(limit, (int, float))
                or limit <= 1
            ):
                raise ValueError("战斗规格.行动效率上限必须是大于 1 的数字")
        for field in ("同时承受控制上限", "控制持续上限"):
            if field in profile:
                limit = profile[field]
                if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
                    raise ValueError(f"战斗规格.{field}必须是正整数")
        response = profile.get("寡敌应变")
        if response is not None:
            if not isinstance(response, Mapping):
                raise ValueError("战斗规格.寡敌应变必须是字典")
            response = dict(response)
            expected = {"每名额外敌人行动效率", "行动效率增量上限"}
            unknown = set(response) - expected
            if unknown:
                raise ValueError(
                    "战斗规格.寡敌应变存在未知字段："
                    + "、".join(sorted(str(item) for item in unknown))
                )
            for field in expected:
                number = response.get(field, 0)
                if (
                    isinstance(number, bool)
                    or not isinstance(number, (int, float))
                    or number < 0
                ):
                    raise ValueError(f"战斗规格.寡敌应变.{field}必须是非负数字")
            profile["寡敌应变"] = response
        return profile

    def _technique_rules(self, techniques, attributes):
        skills, passives = [], []
        for instance in sorted(
            techniques, key=lambda value: int(value.get("出生序号", 0))
        ):
            for index, raw in enumerate(instance.get("能力") or ()):
                node = dict(raw)
                executor = self.catalog.parse_node(node).executor
                handler = self._assembly_handlers.get(executor)
                if handler is None:
                    raise ValueError(f"战斗核心未实现装配执行器：{executor}")
                handler(instance, index, node, attributes, skills, passives)
        skills.sort(key=self._skill_order_key)
        passives.sort(
            key=lambda value: (
                int(value.get("结算顺序", 1)),
                int(value.get("装配位序", 0)),
                str(value.get("物品编号") or ""),
                int(value.get("能力序号", 0)),
                int(value.get("效果序号", 0)),
            )
        )
        return tuple(skills), tuple(passives)

    @staticmethod
    def _assemble_attributes(instance, index, node, attributes, skills, passives):
        del index, skills, passives
        multiplier = float(instance.get("威力倍率", 1))
        for key, value in dict(node.get("属性") or {}).items():
            attributes[str(key)] = (
                attributes.get(str(key), 0) + float(value) * multiplier
            )

    @staticmethod
    def _assemble_active_skill(instance, index, node, attributes, skills, passives):
        del attributes, passives
        source_name = str(instance.get("功法") or instance.get("名称") or "能力")
        source_id = str(instance.get("编号") or source_name)
        skills.append(
            Skill(
                key=f"{instance.get('实例', source_name)}:{index}",
                name=str(node.get("名称") or source_name),
                born_order=int(instance.get("出生序号", 0)),
                release_order=int(node.get("释放顺序", index + 1)),
                source_id=source_id,
                source_category=str(instance.get("来源类别") or "功法"),
                build_instance=str(instance.get("实例") or ""),
                ability_order=index,
                multiplier=float(instance.get("威力倍率", 1)),
                spirit_cost=max(0.0, float(node.get("精神消耗", 0))),
                cooldown_actions=max(0, int(node.get("冷却行动", 0))),
                effects=tuple(copy.deepcopy(node.get("效果") or ())),
                tags=tuple(str(value) for value in node.get("标签") or ()),
                costs=tuple(copy.deepcopy(node.get("额外代价") or ())),
                use_limit=max(0, int(node.get("使用次数", 0))),
                cooldown_group=str(node.get("共享冷却") or ""),
                rollback_on_failure=bool(node.get("失败时回滚", False)),
                element_composition=copy.deepcopy(
                    dict(node.get("属性构成") or instance.get("属性构成") or {"无相": 100})
                ),
            )
        )

    @staticmethod
    def _assemble_passive_skill(instance, index, node, attributes, skills, passives):
        del attributes, skills
        source_name = str(instance.get("功法") or instance.get("名称") or "能力")
        source_id = str(instance.get("编号") or source_name)
        born_order = int(instance.get("出生序号", 0))
        for effect_index, raw in enumerate(node.get("效果") or ()):
            passives.append(
                {
                    "监听键": f"{source_name}:{index}:{effect_index}",
                    "来源能力": str(node.get("名称") or source_name),
                    "结算顺序": int(node.get("结算顺序", 1)),
                    "装配位序": born_order,
                    "物品编号": source_id,
                    "来源类别": str(instance.get("来源类别") or "功法"),
                    "构筑实例": str(instance.get("实例") or ""),
                    "属性构成": copy.deepcopy(
                        dict(node.get("属性构成") or instance.get("属性构成") or {"无相": 100})
                    ),
                    "能力序号": index,
                    "效果序号": effect_index,
                    "词条": copy.deepcopy(dict(instance.get("词条") or {})),
                    "节点": copy.deepcopy(dict(raw)),
                }
            )

    def _normalize_attributes(self, values):
        result = {}
        for key, definition in self.catalog.attributes.items():
            value = float(values.get(key, definition.get("默认值", 0)))
            minimum = float(definition.get("最低值", -math.inf))
            maximum = float(definition.get("最高值", math.inf))
            unit = max(0.0, float(definition.get("最小单位", 0)))
            value = self._clamp(value, minimum, maximum)
            if unit:
                value = round(value / unit) * unit
            result[str(key)] = value
        return result

    def _recover_at_action_start(self, context, actor):
        for resource, attribute in dict(
            self.catalog.action_rules.get("行动开始恢复") or {}
        ).items():
            amount = actor.value(str(attribute), 0)
            if amount > 0:
                self._ability_recover_resource(
                    context,
                    actor,
                    actor,
                    {
                        "目标": {"能力": "选择目标", "范围": "自身"},
                        "资源": resource,
                        "数值": amount,
                        "标签": ["自然恢复"],
                    },
                    1,
                )

    def _tick_cooldowns(self, context, fighter):
        decrement = int(self.catalog.action_rules["技能冷却"]["推进"]["每次减少"])
        for key in tuple(fighter.cooldowns):
            before = fighter.cooldowns[key]
            after = max(0, before - decrement)
            fighter.cooldowns[key] = after
            skill = self._skill_by_key(fighter, key)
            context.event(
                "技能冷却变化后",
                fighter,
                fighter,
                f"{skill.name if skill else key}冷却推进",
                after - before,
                values={
                    "技能": skill.name if skill else key,
                    "技能键": key,
                    "变化前数值": before,
                    "变化后数值": after,
                },
            )
            if before > 0 and after == 0:
                context.event(
                    "技能冷却完成后",
                    fighter,
                    fighter,
                    f"{skill.name if skill else key}冷却完成",
                    values={"技能": skill.name if skill else key, "技能键": key},
                )

    def _skill_spirit_cost(self, actor, skill):
        return max(
            0.0, skill.spirit_cost * max(0.0, 1 - self._percent(actor, "精神消耗修正"))
        )

    def _cast_skill(
        self,
        context,
        actor,
        target,
        skill,
        *,
        triggered=False,
        ignore_cost=False,
        ignore_cooldown=False,
        multiplier=1.0,
    ):
        """施放一门技能：过闸、付代价、跑效果、落冷却；任一步失败都按原因播报。"""

        if (
            skill is None
            or skill.disabled
            or (skill.use_limit and skill.uses >= skill.use_limit)
        ):
            return False
        spirit_cost = self._skill_spirit_cost(actor, skill)
        if self._skill_cast_refused(
            context,
            actor,
            target,
            skill,
            spirit_cost,
            ignore_cost=ignore_cost,
            ignore_cooldown=ignore_cooldown,
        ):
            return False
        frame = self._announce_skill_cast(
            context,
            actor,
            target,
            skill,
            spirit_cost,
            triggered=triggered,
            kind="技能施放前",
        )
        if frame.cancelled:
            self._skill_cast_failed(
                context, actor, target, skill, "被取消", tags=skill.tags
            )
            return False
        target = frame.target
        snapshot = self._transaction_snapshot(context)
        if not self._pay_skill_costs(
            context,
            actor,
            target,
            skill,
            spirit_cost,
            snapshot,
            ignore_cost=ignore_cost,
        ):
            return False
        success = self._run_skill_effects(context, actor, target, skill, multiplier)
        if not success and skill.rollback_on_failure:
            self._restore_transaction(context, snapshot)
            self._skill_cast_failed(
                context, actor, target, skill, "技能前置条件未满足", tags=skill.tags
            )
            return False
        cooldown = self._skill_cooldown(actor, skill)
        if not ignore_cooldown:
            self._apply_skill_cooldown(actor, skill, cooldown)
        skill.uses += 1
        self._announce_skill_cast(
            context,
            actor,
            target,
            skill,
            spirit_cost,
            triggered=triggered,
            kind="技能施放后",
        )
        return success

    def _skill_cast_refused(
        self,
        context,
        actor,
        target,
        skill,
        spirit_cost,
        *,
        ignore_cost,
        ignore_cooldown,
    ) -> bool:
        """过不了闸返回 `True` 并播报原因；冷却未好是**静默**拒绝，不播报。"""

        if self._action_restricted(actor, "技能"):
            self._skill_cast_failed(context, actor, target, skill, "行动限制")
            return True
        if not ignore_cooldown and actor.cooldowns.get(skill.key, 0) > 0:
            return True
        if not ignore_cost and actor.spirit < spirit_cost:
            self._skill_cast_failed(context, actor, target, skill, "精神不足")
            return True
        return False

    def _skill_cast_failed(
        self, context, actor, target, skill, reason: str, *, tags=()
    ) -> None:
        """播报一次施放失败。原因写在 values 里，前端按它取文案。"""

        self._dispatch_event(
            context,
            kind="技能施放失败后",
            source=actor,
            target=target,
            values={"技能": skill.name, "技能键": skill.key, "原因": reason},
            tags=tags,
        )

    def _announce_skill_cast(
        self, context, actor, target, skill, spirit_cost, *, triggered, kind
    ):
        """播报一次施放事件，返回事件帧。「施放前」与「施放后」同构，只有 kind 不同，
        所以载荷只写一份——两处各写一份时，改了一个必忘另一个。
        """

        return self._dispatch_event(
            context,
            kind=kind,
            source=actor,
            target=target,
            values={
                "技能": skill.name,
                "技能键": skill.key,
                "精神消耗": spirit_cost,
                "行动类型": "触发技能" if triggered else "技能",
            },
            tags=skill.tags,
        )

    def _pay_skill_costs(
        self, context, actor, target, skill, spirit_cost, snapshot, *, ignore_cost
    ) -> bool:
        """先付精神、再付额外代价；任一项不足就回滚本次事务并播报。"""

        if ignore_cost:
            return True
        if spirit_cost > 0 and not self._ability_consume_resource(
            context,
            actor,
            actor,
            {
                "目标": {"能力": "选择目标", "范围": "自身"},
                "资源": "精神",
                "数值": spirit_cost,
                "不足时是否失败": True,
            },
            1,
        ):
            self._restore_transaction(context, snapshot)
            return False
        for cost in skill.costs:
            if not self._execute_mechanism(
                context, actor, target, dict(cost), skill.multiplier
            ):
                self._restore_transaction(context, snapshot)
                self._skill_cast_failed(
                    context, actor, target, skill, "额外代价不足", tags=skill.tags
                )
                return False
        return True

    def _run_skill_effects(self, context, actor, target, skill, multiplier) -> bool:
        """跑完技能的全部效果，返回是否全部成功。

        期间把「当前能力 / 构筑实例 / 五行构成」换成这门技能的，好让效果里的取值
        读到正确的来源；无论成败都在 `finally` 里还原。
        """

        actor.current_skill = skill.key
        previous_composition = context.current_element_composition
        previous_ability = context.current_ability
        previous_instance = context.current_build_instance
        context.current_ability = skill.name
        context.current_build_instance = skill.build_instance
        context.current_element_composition = dict(skill.element_composition)
        success = True
        try:
            for node in skill.effects:
                success = (
                    self._execute_mechanism(
                        context,
                        actor,
                        target,
                        dict(node),
                        skill.multiplier * multiplier,
                    )
                    and success
                )
        finally:
            actor.current_skill = ""
            context.current_ability = previous_ability
            context.current_build_instance = previous_instance
            context.current_element_composition = previous_composition
        return success

    def _skill_cooldown(self, actor, skill) -> int:
        """这门技能本次要落的冷却行动数（已按冷却缩减与余数处理折算）。"""

        reduction = self._clamp(self._percent(actor, "冷却缩减"), -5, 0.8)
        raw_cooldown = skill.cooldown_actions * (1 - reduction)
        rounding = self.catalog.action_rules["技能冷却"]["余数处理"]
        return max(
            0,
            math.ceil(raw_cooldown) if rounding == "向上取整" else int(raw_cooldown),
        )

    def _apply_skill_cooldown(self, actor, skill, cooldown: int) -> None:
        """落冷却；带冷却组的技能会把同组技能一起压到不低于本次冷却。"""

        if not cooldown:
            return
        actor.cooldowns[skill.key] = cooldown
        if skill.cooldown_group:
            for other in actor.skills:
                if other.cooldown_group == skill.cooldown_group:
                    actor.cooldowns[other.key] = max(
                        actor.cooldowns.get(other.key, 0), cooldown
                    )

    def _basic_attack(self, context, source, target):
        if self._action_restricted(source, "普通攻击"):
            return False
        frame = self._dispatch_event(
            context,
            kind="普通攻击前",
            source=source,
            target=target,
            values={"行动类型": "普通攻击"},
            tags=("普通攻击",),
        )
        if frame.cancelled:
            return False
        target = frame.target
        power = max(0.0, self._percent(source, "普通攻击威力"))
        applied = self._deal_attack(
            context, source, target, power, "普通攻击", tags=("普通攻击",)
        )
        self._dispatch_event(
            context,
            kind="普通攻击后",
            source=source,
            target=target,
            amount=applied,
            values={"实际数值": applied, "行动类型": "普通攻击"},
            tags=("普通攻击",),
        )
        return True

    @staticmethod
    def _action_restricted(fighter, action):
        return any(
            "行动" in status.action_limits or action in status.action_limits
            for status in fighter.statuses
        )

    def _deal_attack(
        self,
        context,
        source,
        target,
        power,
        label,
        *,
        damage_form="直接",
        defense_rule="普通",
        tags=(),
        can_miss=True,
        can_critical=True,
        can_block=True,
        allow_followups=True,
        raw_amount=None,
        can_lifesteal=True,
    ):
        raw = max(
            0.0,
            float(raw_amount)
            if raw_amount is not None
            else source.value("攻击", 1) * max(0.0, float(power)),
        )
        resolution = self._apply_damage(
            context,
            source,
            target,
            raw,
            label=label,
            damage_form=damage_form,
            defense_rule=defense_rule,
            can_miss=can_miss,
            can_critical=can_critical,
            can_block=can_block,
            tags=tuple(tags),
        )
        if can_lifesteal and resolution.health_damage > 0 and source.alive:
            rate = self._percent(source, "吸血率")
            if rate > 0:
                self._ability_recover_resource(
                    context,
                    source,
                    source,
                    {
                        "目标": {"能力": "选择目标", "范围": "自身"},
                        "资源": "血气",
                        "数值": resolution.health_damage * rate,
                    },
                    1,
                )
        if (
            allow_followups
            and resolution.actual_damage > 0
            and target.alive
            and self._judgement(context, "连击", self._percent(source, "连击率"))
        ):
            self._deal_attack(
                context,
                source,
                target,
                power * self._percent(source, "连击伤害"),
                "连击",
                tags=(*tags, "连击", "派生伤害"),
                allow_followups=False,
            )
        return resolution.actual_damage

    def _apply_damage(
        self,
        context,
        source,
        target,
        amount,
        *,
        ignore_defense=False,
        label="伤害",
        damage_form="直接",
        defense_rule="普通",
        can_miss=False,
        can_critical=True,
        can_block=True,
        tags=(),
        allow_reactions=True,
    ):
        effective_rule = (
            "无视防御" if ignore_defense and defense_rule == "普通" else defense_rule
        )
        judgement = self._dispatch_event(
            context,
            kind="命中判定前",
            source=source,
            target=target,
            amount=amount,
            values={"行动类型": damage_form, "伤害名称": label},
            tags=tags,
        )
        tags = tuple(judgement.tags)
        allow_critical = can_critical
        if allow_critical:
            judgement = self._dispatch_event(
                context,
                kind="暴击判定前",
                source=source,
                target=target,
                amount=amount,
                values={
                    "暴击率": self._percent(source, "暴击率"),
                    "行动类型": damage_form,
                },
                tags=tags,
            )
            tags = tuple(judgement.tags)
            allow_critical = not judgement.cancelled
        if can_block and effective_rule != "真实":
            judgement = self._dispatch_event(
                context,
                kind="格挡判定前",
                source=source,
                target=target,
                amount=amount,
                values={
                    "格挡率": self._percent(target, "格挡率"),
                    "行动类型": damage_form,
                },
                tags=tags,
            )
            tags = tuple(judgement.tags)
        resolution = self.damage.resolve(
            DamageRequest(
                amount=max(0.0, float(amount)),
                label=label,
                damage_form=damage_form,
                defense_rule=effective_rule,
                tags=tags,
                can_miss=can_miss,
                can_critical=allow_critical,
                can_block=can_block,
            ),
            source=source,
            target=target,
            rng=context.rng,
            judge=lambda kind, chance, roll: self._judgement(
                context, kind, chance, roll
            ),
        )
        if not resolution.hit:
            self._dispatch_event(
                context,
                kind="闪避后",
                source=source,
                target=target,
                values=resolution.values(),
                tags=tags,
            )
            return resolution
        self._dispatch_event(
            context,
            kind="命中后",
            source=source,
            target=target,
            amount=resolution.breakdown.limited,
            values=resolution.values(),
            tags=tags,
        )
        pre = self._dispatch_event(
            context,
            kind="造成伤害前",
            source=source,
            target=target,
            amount=resolution.breakdown.limited,
            values={**resolution.values(), "当前数值": resolution.breakdown.limited},
            tags=tags,
        )
        tags = tuple(pre.tags)
        if pre.target is not target:
            target = pre.target
            resolution = self.damage.resolve(
                resolution.request,
                source=source,
                target=target,
                rng=context.rng,
                judge=lambda kind, chance, roll: self._judgement(
                    context, kind, chance, roll
                ),
            )
        if "伤害" in self._immunities(target):
            pre.cancelled = True
        target_was_alive = target.alive
        resolution = self.damage.with_limited_damage(
            resolution, 0 if pre.cancelled else pre.amount
        )
        if resolution.defeated:
            fatal = self._dispatch_event(
                context,
                kind="受到致命伤害",
                source=source,
                target=target,
                amount=resolution.actual_damage,
                values=resolution.values(),
                tags=tags,
            )
            if fatal.cancelled:
                resolution = self.damage.with_minimum_health(
                    resolution, float(fatal.facts.get("保留血气", 1))
                )
        target.shield = resolution.shield_after
        target.health = resolution.health_after
        values = resolution.values()
        values["伤害名称"] = resolution.request.label
        values["实际数值"] = resolution.actual_damage
        if resolution.critical:
            self._dispatch_event(
                context,
                kind="暴击后",
                source=source,
                target=target,
                amount=resolution.actual_damage,
                values=values,
                tags=tags,
            )
        if resolution.blocked:
            self._dispatch_event(
                context,
                kind="格挡后",
                source=source,
                target=target,
                amount=resolution.actual_damage,
                values=values,
                tags=tags,
            )
        if resolution.shield_damage > 0:
            self._dispatch_event(
                context,
                kind="护盾吸收后",
                source=source,
                target=target,
                amount=resolution.shield_damage,
                values=values,
                tags=tags,
            )
        self._dispatch_event(
            context,
            kind="造成伤害后",
            source=source,
            target=target,
            amount=resolution.actual_damage,
            values=values,
            tags=tags,
        )
        self._dispatch_event(
            context,
            kind="受到伤害后",
            source=source,
            target=target,
            amount=resolution.actual_damage,
            values=values,
            tags=tags,
        )
        self._absorb_field_damage(context, source, target, resolution.actual_damage)
        if resolution.shield_broken:
            self._dispatch_event(
                context,
                kind="护盾破碎后",
                source=source,
                target=target,
                amount=resolution.shield_damage,
                values=values,
                tags=tags,
        )
        if target_was_alive and not target.alive:
            target.spirit = 0
            self._dispatch_event(
                context,
                kind="死亡后",
                source=source,
                target=target,
                amount=resolution.actual_damage,
                values=values,
                tags=tags,
            )
            if target.combatant_type == "构造物" or target.summoned:
                self._retire_battle_object(
                    context,
                    source,
                    target,
                    "构造物" if target.combatant_type == "构造物" else "参战者",
                )
            else:
                self._remove_source_lifetimes(context, target)
            if not target.alive:
                self._dispatch_event(
                    context,
                    kind="击杀后",
                    source=source,
                    target=target,
                    amount=resolution.actual_damage,
                    values=values,
                    tags=tags,
                )
        if (
            allow_reactions
            and resolution.actual_damage > 0
            and damage_form == "直接"
            and source is not target
        ):
            reflect = resolution.actual_damage * self._percent(target, "反伤率")
            if reflect > 0 and source.alive:
                self._apply_damage(
                    context,
                    target,
                    source,
                    reflect,
                    label="反伤",
                    damage_form="反伤",
                    defense_rule="真实",
                    can_critical=False,
                    can_block=False,
                    tags=("反伤", "派生伤害"),
                    allow_reactions=False,
                )
            if (
                source.alive
                and target.alive
                and self._judgement(context, "反击", self._percent(target, "反击率"))
            ):
                self._deal_attack(
                    context,
                    target,
                    source,
                    1,
                    "反击",
                    tags=("反击", "派生伤害"),
                    allow_followups=False,
                )
        return resolution

    def _advance_lifecycles(self, context, actor):
        kept = []
        for status in actor.statuses:
            if status.duration_unit == "状态承受者行动":
                status.remaining_turns -= 1
            if status.remaining_turns > 0 or status.duration_unit == "整场战斗":
                kept.append(status)
            else:
                context.event(
                    "移除状态后",
                    actor,
                    actor,
                    f"{status.name}消散",
                    values={"状态": status.name, "原因": "到期"},
                    tags=status.tags,
                )
        if len(kept) != len(actor.statuses):
            context.mark_listener_index_dirty()
        actor.statuses = kept
        for obj in list(context.combat_objects.values()):
            if obj.remaining_actions > 0:
                obj.remaining_actions -= 1
                if obj.remaining_actions == 0:
                    context.combat_objects.pop(obj.id, None)
                    context.mark_listener_index_dirty()
                    shell = context.fighter_by_id(obj.id)
                    if shell is not None:
                        shell.active = False
                        shell.health = 0
                    context.event(
                        "战斗对象退场后",
                        actor,
                        shell or actor,
                        f"{obj.name}消散",
                        values={"对象ID": obj.id, "对象类型": obj.object_type},
                    )

    def _use_medicine(self, context, fighter):
        if not fighter.auto_medicine:
            return
        for resource in ("血气", "精神"):
            current, maximum = self._resource_values(fighter, resource)
            if maximum <= 0 or current / maximum >= fighter.medicine_threshold:
                continue
            candidates = []
            for item_id, quantity in fighter.inventory.items():
                medicine = context.medicine_definitions.get(item_id)
                if (
                    quantity > 0
                    and medicine is not None
                    and medicine.resource == resource
                ):
                    amount = maximum * medicine.recovery_percent / 100.0
                    candidates.append((amount, medicine.grade_order, item_id))
            if not candidates:
                continue
            if context.medicine_selection_strategy != "缺口优先":
                raise ValueError("战斗不支持该恢复丹选药策略")
            gap = maximum - current
            filling = [candidate for candidate in candidates if candidate[0] >= gap]
            if filling:
                amount, _, item_id = min(
                    filling,
                    key=lambda value: (value[0] - gap, value[1], value[2]),
                )
            else:
                amount, _, item_id = min(
                    candidates,
                    key=lambda value: (-value[0], value[1], value[2]),
                )
            fighter.inventory[item_id] -= 1
            fighter.consumed_items[item_id] = fighter.consumed_items.get(item_id, 0) + 1
            before, _ = self._resource_values(fighter, resource)
            self._ability_recover_resource(
                context,
                fighter,
                fighter,
                {
                    "目标": {"能力": "选择目标", "范围": "自身"},
                    "资源": resource,
                    "数值": amount,
                },
                1,
            )
            after, _ = self._resource_values(fighter, resource)
            medicine = context.medicine_definitions[item_id]
            context.event(
                "使用丹药后",
                fighter,
                fighter,
                f"{fighter.name}服用丹药恢复{resource}",
                after - before,
                values={
                    "丹药编号": medicine.medicine_id,
                    "品级编号": medicine.grade_id,
                    "堆叠键": item_id,
                    "资源": resource,
                    "恢复比例": medicine.recovery_percent,
                    "变化前数值": before,
                    "变化后数值": after,
                    "实际数值": after - before,
                },
                tags=("丹药", "恢复", resource),
            )
