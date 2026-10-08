"""由原子能力 JSON 驱动的通用战斗执行器。"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence, Mapping
from .models import (
    BattleContext,
    CombatObject,
    EventFrame,
    Fighter,
    Skill,
    StatusState,
    ModifierMap,
    compile_definition_copy,
    copy_skills,
    copy_value,
    record_values,
    same_definition,
)

import bisect
import copy
import math
from itertools import chain, filterfalse
from operator import attrgetter, itemgetter
from typing import Any

from .contracts import BattleEvent
from .chains import ChainRuntime, response_level
from .foundation import EVENT_LISTENER_SORT_ORDER

#: 目标范围名 -> `_target_select` 里的分支名。
#: 这张表是**唯一出处**：`TARGET_SCOPES` 与作用域校验都从它派生，不许另抄一份。
TARGET_SCOPES: Mapping[str, str] = {
    "自身": "self",
    "当前目标": "current",
    "效果来源": "effect_source",
    "事件来源": "event_source",
    "事件承受者": "event_target",
    "行动者": "actor",
    "己方": "allies",
    "敌方": "enemies",
    "全体": "everyone",
    "任意": "anyone",
    "关联对象": "related",
    "主人": "owner",
    "控制者": "controller",
    "本编组主战者": "group_leader",
}

#: 目标字段省略时指向谁。
#:
#: 必须是「当前目标」，因为各调用点传进来的 `target` 语义不同：多数是出效果者自身，
#: 但 `来源目标`/`接收目标`/`归属目标` 以及遍历选出的目标传的是别的参战者。
#: 实测把它改成「自身」会让 19 张功法改变行为（1967 场语料对照：1948 一致 / 19 差异），
#: 所以省略的缺省语义**必须与原实现一致**；「自身」只在显式写出时才生效。
DEFAULT_TARGET_SCOPE = "当前目标"

#: 目标字段使用的原子能力名。`parse_node` 按 `能力` 取执行器，所以缺省 selector
#: 必须自带这个键，不能只写 `范围`。
TARGET_SELECTOR_ABILITY = "选择目标"

#: 范围名 -> 该范围的 selector 对象。**同一范围永远给同一个对象**：`parse_node` 按对象
#: 身份记忆化，简写范围（"自身"、"当前目标"…）每次现造一个字典就等于每次都缓存不中。
_SCOPE_SELECTORS: Mapping[str, dict[str, Any]] = {
    scope: {"能力": TARGET_SELECTOR_ABILITY, "范围": scope} for scope in TARGET_SCOPES
}

#: 「只有 `范围`（外加可选的 `能力`）」的 selector——`_target_select` 走**快路**的判据。
#:
#: 这种 selector 后面那六个字段（`生存状态` / `排除自身` / `身份` / `对象类型` / `拥有状态` /
#: `排序`）全是缺省值，而缺省只做两件事——「存活」与「非构造物」——再加规则层那一问；快路就按
#: 那三件事算，省掉六趟 `selector.get`、五次 `str()`、四次列表重建与 `排序 / 数量` 的取值切片。
#: `_SCOPE_SELECTORS` 里那些对象就是这一形态；「选择目标」的完整写法会先过 `parse_node`，
#: 到 `_target_select` 时已经是另一份 `dict`，不会误判。
#:
#: **给「选择目标」添新的默认字段时，`_target_select` 的快路必须一起改**——所以这张集合与快路
#: 写在同一个文件、紧挨着，改一处就能看见另一处。实测：一场 12,383 次调用里 11,682 次（94.3%）
#: 走快路，单次 6,723.7 → 5,674.8 ns。
_TARGET_SELECTOR_BARE_KEYS = frozenset({"能力", "范围"})


#: 排序键里的「位次」取法：候选合并按位次排（见 `_listeners_for`）。
#: 用 `itemgetter` 而不是 lambda：键就是条目元组的第 0 项，C 层取法省掉一层 Python 帧。
_POSITION = itemgetter(0)

#: 监听条目的**字段布局唯一出处**（`_ListenerSink.add` 按这个次序造，`_dispatch_event` 按同一
#: 次序解包读）。加新字段（比如把解析好的 `RuleNode`、预计算的名额上限带下去）**一律追加在末尾**，
#: 不许插队——第 0 项是**排序键里的位次**，插队会静默改结算先后；读处用解包而不是下标，插队比
#: 追加更容易漏改一处。长度与次序由 `_validate_listener_entries` 在**每次真重建后逐条核**，
#: 核不过就抛错（宁可当场报错，不许静默错位）。
_LISTENER_ENTRY_FIELDS = (
    "位次",
    "持有者",
    "触发编号",
    "名额键",
    "来源能力",
    "构筑实例",
    "节点",
    "元素构成",
    "条件",
    "行动上限",
    "战斗上限",
    "效果",
    "条件确定性",
    "激活键",
    "响应等级",
    "根链上限",
    "结算阶段",
    "同源根链上限",
)
_LISTENER_ENTRY_LEN = len(_LISTENER_ENTRY_FIELDS)


def _validate_listener_entries(ordered: Mapping[str, tuple]) -> None:
    """每次真重建后逐条核监听条目的长度：布局一处定义、一处校验（规矩 ⑥）。"""

    for event_name, entries in ordered.items():
        for entry in entries:
            if len(entry) != _LISTENER_ENTRY_LEN:
                raise ValueError(
                    f"监听条目布局不合：事件 {event_name} 上有 {len(entry)} 个字段，"
                    f"应为 {_LISTENER_ENTRY_LEN}（{_LISTENER_ENTRY_FIELDS}）"
                )


class _CandidateList(list):
    """`_listeners_for` 交出来的候选表，额外记住「这份是在哪一版监听表上按关系判定筛过的」。

    派发循环拿到它以后，只要监听表版本没变就不用再逐候选问一遍关系（`已筛`）；
    版本一变（换阵营 / 重建索引导致换表）就整体退回逐条判定。缺这个属性的普通 `list`
    （`tools/监听收窄对照.py` 就把 `_listeners_for` 整体换成一个 `list`）按「未筛」处理，
    语义与从前逐条判定完全一致。

    **给新加的派发点的一句话**：拿到候选表**别假设它一定筛过**——它可能是普通 `list`
    （护栏工具换过、或关系判定抛错走了未筛兜底），也可能是上个版本筛的。只须照
    `_dispatch_event` 的写法比一次 `filtered_version != context.listener_table_version`，
    对不上就逐条问；反过来「当它一定筛过、于是干脆不判定」会**静默漏触发**。
    """

    __slots__ = ("filtered_version", "uncapped", "count_stamp")

    def __init__(self, values: Iterable[tuple[int, Any]]=(), *, filtered_version: int) -> None:
        super().__init__(values)
        self.filtered_version = filtered_version
        self.uncapped = None
        self.count_stamp = None

    def available(self, context: BattleContext) -> list[tuple[int, Any]]:
        # 短表也可能在名额耗尽后被重复派发数千次；同样缓存耗尽结果，
        # 让空候选直接返回，不再反复进事件栈和逐条检查名额。
        if not self:
            return self
        stamp = self.count_stamp
        budget_version = context.listener_budget_version
        if (stamp is None or stamp[0] != context.action_number
                or stamp[1] is not context.trigger_counts or stamp[2] is not context.battle_trigger_counts
                or stamp[3] != context.chain_serial or stamp[4] is not context.chain_counts
                or stamp[6] is not context.support_window):
            self.uncapped = None
        elif (self.uncapped is not None and not self.uncapped) or stamp[5] == budget_version:
            # 没有新监听耗尽名额，上一轮筛选结果仍有效。长候选表会在同一根链内经历很多
            # 没有监听成功的事件；不必为这些事件重复扫描整张候选表。
            # 若整表已经耗尽，其他监听继续耗费名额也不会使本表重新可用。
            return self if self.uncapped is None else self.uncapped
        # 同一行动/根链中名额单调消耗，只需复筛上次尚未耗尽的条目。
        # 回滚会替换计数字典，上面的身份检查会恢复整表。
        self.count_stamp = (context.action_number, context.trigger_counts, context.battle_trigger_counts,
                            context.chain_serial, context.chain_counts, budget_version, context.support_window)
        counts = context.trigger_counts
        battle_counts = context.battle_trigger_counts
        chain_counts = context.chain_counts
        support_counts = context.support_window
        values = self if self.uncapped is None else self.uncapped
        uncapped = [pair for pair in values if not (
            chain_counts.get(pair[1][13], 0) >= (
                pair[1][15] if len(pair[1]) > 15
                else int((pair[1][6] or {}).get("每条根链最多触发", 1) or 0)
            ) > 0
        ) and (not pair[1][12] or not (
            pair[1][9] and counts.get(pair[1][13], 0) >= pair[1][9]
            or pair[1][10] and battle_counts.get(pair[1][13], 0) >= pair[1][10]))
            and not (
                (limit := int((pair[1][6] or {}).get("自身行动间隔最多触发", 0) or 0))
                and support_counts.get(pair[1][13], 0) >= limit
            )]
        if len(uncapped) != len(values):
            self.uncapped = uncapped
        return self if self.uncapped is None else self.uncapped


class _ListenerSink:
    """监听汇总口：把各处声明的监听收成「事件 → 监听列表」，并算好排序键与名额键。

    单独成一个对象是因为五路来源（被动、状态、战场环境、战斗对象、战场规则）都要往
    同一张表里写，而键的构造规则只该有一份。
    """

    #: 排序键里「参战位序」那一项的下标：**由 `foundation.EVENT_LISTENER_SORT_ORDER`
    #: 算出来**，不写字面量。那张单子是排序键布局的唯一出处（启动期按顺序逐字校验），
    #: 所以加减字段时这里跟着走；`_passive_listener_entries` 的「按位次重拼」用的就是这个
    #: 下标，写死会静默错位。
    PARTICIPANT_ORDER_INDEX: int = EVENT_LISTENER_SORT_ORDER.index("参战位序")

    def __init__(
        self,
        engine: Any,
        order: tuple[str, ...],
        participant_order: Mapping[str, Any],
        participant_order_fallback: Any = None,
    ) -> None:
        self.engine = engine
        self.order = order
        self.participant_order = participant_order
        self.participant_order_fallback = len(participant_order) if participant_order_fallback is None else participant_order_fallback
        self.grouped: dict[str, list[tuple[Any, ...]]] = {}

    def add(
        self,
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
        """收一条监听；没有 `事件` 的节点不是监听，直接丢。"""

        event_name = str(node.get("事件") or "")
        if not event_name:
            return
        activation_id = (
            f"{build_instance}:{item_id}:{listener_id}:{ability_order}:{effect_order}"
            if item_id
            else f"{build_instance}:{listener_id}"
        )
        # `每次行动最多触发` 的名额属于**声明**，不属于那一张卡：同一个修士带两张
        # 同名词条时，它们是同一条声明，共用同一个名额（游戏王 HOPT 的口径）。
        # 所以名额键里刻意不含 `build_instance`——那才是区分「第几张」的东西，
        # 含上它等于每张卡各给一个名额，卡面写的「每行动只能使用1次」就被翻倍了。
        # 名额**按修士**算，不跨方合并：对面的同名词条是另一份名额。
        activation_budget = (
            f"{item_id}:{listener_id}:{ability_order}:{effect_order}"
            if item_id
            else listener_id
        )
        # 排序键按 `self.order` 的先后直接拼出来（不进一层 `values` 字典）：
        # `order` 里的字段名与下面这个元组**逐位对应**（`能力序号` 那一位摊成
        # `(能力序号, 效果序号)` 一对）。这张布局的出处是 `foundation.EVENT_LISTENER_SORT_ORDER`，
        # 启动期按顺序逐字校验过；改那张单子时这里要跟着改（`PARTICIPANT_ORDER_INDEX` 自动跟着走）。
        key = (
            -response_level(node),
            self.engine._source_layer(source_category),
            -int(node.get("优先级", 0)),
            int(settlement_order),
            self.participant_order.get(owner.id, self.participant_order_fallback),
            int(build_order),
            str(item_id),
            (int(ability_order), int(effect_order)),
            activation_id,
        )
        self.grouped.setdefault(event_name, []).append(
            (
                key,
                owner,
                activation_id,
                activation_budget,
                str(source_ability),
                str(build_instance),
                node,
                dict(element_composition or {"无相": 100}),
                node.get("条件") or (),
                int(node.get("每次行动最多触发", 0) or 0),
                int(node.get("每场战斗最多触发", 0) or 0),
                node.get("效果") or (),
                self.engine._listener_conditions_deterministic(node.get("条件") or ()),
                (owner.id, activation_budget),
                response_level(node),
                int(node.get("每条根链最多触发", 1) or 0),
                str(node.get("结算阶段") or ""),
                int(node.get("同一事件来源每条根链最多触发", 0) or 0),
            )
        )


class AbilityRuntime(ChainRuntime):
    """只实现组合语义，不决定具体功法内容。"""

    MAX_EVENT_DEPTH = 32
    MAX_ABILITY_DEPTH = 64
    MAX_REPEAT = 100
    MAX_TRIGGERED_SKILLS = 8
    _condition_type_aliases = {"资源类型": "资源", "行动类型": "行动类型", "技能类型": "技能类型"}
    _executors_using_event_context = frozenset({
        "顺序执行", "条件执行", "随机执行", "遍历目标", "重复执行", "尝试执行", "事务执行",
        "造成伤害", "恢复资源", "消耗资源", "支付代价", "设置资源", "转移资源",
        "转移状态", "修改构筑计量", "转移伤害", "修改事件数值", "记录战斗事实",
        "保存结果", "回放效果",
    })

    #: `时序.来源层级` 在装配期摊成的「来源 → 序位」（由 `BattleEngine.__init__` 填，
    #: 见 `_source_layer`）。类上先留一份空的：这样任何构造路径下 `_source_layer`
    #: 都只会（在查不到时）报 `ValueError`，不会冒出 `AttributeError`。
    _source_layers: Mapping[str, int] = {}
    _element_generating: Mapping[str, str] = {}
    _element_overcoming: Mapping[str, str] = {}
    _event_names: frozenset[str] = frozenset()
    _event_depth_limit: int = MAX_EVENT_DEPTH
    _ability_depth_limit: int = MAX_ABILITY_DEPTH

    def _execute_mechanism(
        self,
        context: BattleContext,
        source: Fighter,
        target: Fighter,
        effect: Mapping[str, Any],
        multiplier: float = 1.0,
        *,
        event_amount: float = 0.0,
        event_values: Mapping[str, Any] | None = None,
        tags: tuple[str, ...] = (),
    ) -> bool:
        depth_limit = self._ability_depth_limit
        if context.ability_depth >= depth_limit:
            # 到顶不是报错，是**这一层不再往下执行**：一条合法但很深的连锁（返照家族的
            # `资变` ↔ `伤后` 自环会跨 9 张真意叠上去）不该让整场战斗炸掉。留痕，便于事后审。
            frame = self._current_event(context)
            if frame is not None:
                frame.facts["能力链跳过"] = True
            context.last_result = {
                "成功": False,
                "能力链跳过": True,
                "执行器": "未执行",
            }
            return False
        # 执行器只是效果节点的**纯函数**，而同一个节点会被反复执行（监听触发一次执行一次）。
        # 按对象身份缓存 `RuleNode`（命中核 `values is`，与 `CombatCatalog._node_cache` 同一
        # 手法、同一前提：节点装配期冻结、一场里不换），省掉纯调用开销——实测这一处
        # **13,259 次调用 / 11,001 次命中 / 现场 10.9 ms**。交给处理器的仍是下面 `dict(effect)`
        # 那份副本，缓存不碰它。
        # 这里**不必判 `context is None`**：上面已经读过 `context.ability_depth`，真为 None 早炸了。
        cached = context.ability_handler_cache.get(id(effect))
        if cached is None or cached[0] is not effect:
            node = self.catalog.parse_node(effect)
            handler = self._ability_handlers.get(node.executor)
            if handler is None:
                raise ValueError(f"战斗核心未实现执行器：{node.executor or '<空>'}")
            if getattr(handler, '__func__', None) is AbilityRuntime._ability_conditional:
                handler = self._compile_conditional(effect)
            cached = (effect, node, handler, node.executor in self._executors_using_event_context,
                      node.executor in {'造成伤害', '恢复资源'} and '属性构成' not in effect,
                      node.category == '效果' and node.executor not in {'回放效果', '保存结果'})
            context.ability_handler_cache[id(effect)] = cached
        _, node, handler, uses_event, needs_composition, keeps_history = cached
        effective = effect
        if needs_composition and context.current_element_composition:
            effective = dict(effect)
            effective['属性构成'] = dict(context.current_element_composition)
        before_events = context.event_count
        previous_result = context.last_result
        context.ability_depth += 1
        try:
            if uses_event:
                result = handler(
                    context,
                    source,
                    target,
                    effective,
                    multiplier,
                    event_amount=event_amount,
                    event_values=event_values or {},
                    tags=tags if type(tags) is tuple else tuple(tags),
                )
            else:
                result = handler(context, source, target, effective, multiplier)
        finally:
            context.ability_depth -= 1
        success = True if result is None else bool(result)
        # 原子执行器没有产生新详情时清空旧详情；每次都替换对象，让外层组合
        # 执行器能够按身份判断子效果是否产生了结果。原地更新会混入前次伤害。
        details = context.last_result if context.last_result is not previous_result else {}
        context.last_result = {
            **details,
            "成功": success,
            "新增事件数": context.event_count - before_events,
            "能力": node.ability,
            "执行器": node.executor,
        }
        if keeps_history:
            # 执行器只读节点（改写技能/状态都是「先深拷、再换字段」），而读历史的一方
            # （`_ability_replay_effect`）自己会先深拷一份，所以这里不必再拷一次。
            # 失败效果仍占用历史窗口位置以保持淘汰时序，但只留失败标记；回放只读取成功条目。
            context.effect_history.append(
                {
                    "来源": source.id,
                    "目标": target.id,
                    "节点": effective,
                    "倍率": multiplier,
                    "成功": True,
                }
                if success else {"成功": False}
            )
            del context.effect_history[:-100]
        return success

    def _run_effects(self, context: BattleContext, source: Fighter, target: Fighter, effects: Sequence[Mapping[str, Any]], multiplier: float, *,
                     event_amount: float=0.0, event_values: Mapping[str, Any] | None=None, tags: Iterable[str]=()) -> bool:
        # 传**原节点**而不是 `dict(child)`：`_execute_mechanism` 自己会造一份 `effective`
        # 再改，节点本身不动；而 `parse_node` 按对象身份记忆化，每次现造一个字典就等于
        # 每次都缓存不中。
        children = effects or ()
        execute = self._execute_mechanism
        shared_values = event_values or {}
        shared_tags = tags if type(tags) is tuple else tuple(tags)
        for child in children:
            if not execute(
                context, source, target, child, multiplier,
                event_amount=event_amount, event_values=shared_values, tags=shared_tags,
            ):
                return False
        return True

    def _ability_sequence(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
        return self._run_effects(
            context, source, target, effect.get("效果"), multiplier, **kwargs
        )

    def _ability_conditional(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
        conditions = effect.get("条件") or ()
        # 空条件恒成立，先看有没有条件再来问：这一层省掉的是**一次调用与三个实参的求值**，
        # 不是循环体里那点活（见 `_conditions_allow` 的说明）。
        allowed = not conditions or self._conditions_allow(
            context,
            source,
            target,
            conditions,
            kwargs.get("event_amount", 0.0),
            kwargs.get("event_values") or {},
            kwargs.get("tags") or (),
        )
        branch = effect.get("成立效果" if allowed else "不成立效果") or ()
        return self._run_effects(context, source, target, branch, multiplier, **kwargs)

    def _compile_conditional(self, effect: Mapping[str, Any]) -> Callable[..., bool]:
        conditions = effect.get("条件") or ()
        plan = self._compile_condition_sequence(conditions)
        yes, no = effect.get("成立效果") or (), effect.get("不成立效果") or ()
        if all(raw is None for raw, _, _ in plan):
            branch = yes if all(handler for _, handler, _ in plan) else no
            def execute_constant(context: BattleContext, source: Fighter, target: Fighter, _effect: Mapping[str, Any], multiplier: float, *,
                                 event_amount: float=0.0, event_values: Mapping[str, Any] | None=None, tags: Iterable[str]=()) -> bool:
                if not branch:
                    return True
                return self._run_effects(
                    context, source, target, branch, multiplier,
                    event_amount=event_amount, event_values=event_values, tags=tags,
                )
            return execute_constant

        def execute(context: BattleContext, source: Fighter, target: Fighter, _effect: Mapping[str, Any], multiplier: float, *,
                    event_amount: float=0.0, event_values: Mapping[str, Any] | None=None, tags: Iterable[str]=()) -> bool:
            allowed = not conditions or self._evaluate_condition_plan(
                context, source, target, plan, event_amount, event_values or {}, tags
            )
            branch = yes if allowed else no
            if not branch:
                return True
            return self._run_effects(
                context, source, target, branch, multiplier,
                event_amount=event_amount, event_values=event_values, tags=tags,
            )

        return execute

    def _ability_random(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
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

    def _ability_iterate(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
        destinations = self._select_targets(context, source, target, effect.get("目标"))
        if not destinations:
            return False
        ok = True
        for destination in destinations:
            ok = self._run_effects(
                context, source, destination, effect.get("效果"), multiplier, **kwargs
            ) and ok
        return ok

    def _ability_repeat(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
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

    def _ability_attempt(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
        success = self._run_effects(
            context, source, target, effect.get("尝试效果"), multiplier, **kwargs
        )
        branch = effect.get("成功效果" if success else "失败效果") or ()
        self._run_effects(context, source, target, branch, multiplier, **kwargs)
        return success

    def _ability_transaction(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
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
    def _transaction_snapshot(context: BattleContext) -> dict[str, Any]:
        """给「尝试执行」存一份回滚点。

        **别整份 `deepcopy`**：一次尝试要把整场状态拷一遍的话，37 个单位的一场仗光深拷贝就吃掉
        六成时间（实测 12.1M 次 `deepcopy`、42s 里 26s）。这里只存**真会变的那部分**：

        - 标量直接存值（本来就不可变）；
        - 字典字段各拷一层（`attributes` / `cooldowns` / `team_synergy` …）；
        - 状态与技能按对象**浅拷**（改的是 `层数`、`剩余行动`、字段这些标量）；
        - 装配期定死的 `rules`、监听节点直接共享（运行期不原地改）。

        回滚时按同一张清单写回去，并把快照里的容器再拷一层，保证这份回滚点用过还能再用。
        """

        return {
            "fighters": {
                fighter.id: AbilityRuntime._snapshot_fighter(fighter)
                for fighter in context.fighters
            },
            "left_ids": [fighter.id for fighter in context.left_team],
            "right_ids": [fighter.id for fighter in context.right_team],
            # 这几样**结构不固定**（记录值是变长列表、判定覆盖里还嵌字典），浅拷会漏掉嵌套那一层，
            # 回滚就不干净了——实测浅拷会让事件数变（14426 → 18055），所以规矩是：**拿不准就深拷**。
            "records": copy.deepcopy(context.records),
            "relations": copy.deepcopy(context.relations),
            "objects": copy.deepcopy(context.combat_objects),
            "rules": copy.deepcopy(context.battle_rules),
            "progress": dict(context.action_progress),
            "counters": dict(context.ability_counters),
            "saved": copy.deepcopy(context.saved_results),
            "event_count": context.event_count,
            "captured_event_count": len(context.events),
            # 历史窗口会从头淘汰旧条目，不能只保存长度并截尾恢复。
            # 条目发布后只读；回放方另做深拷，因此这里只保存窗口副本。
            "effect_history": list(context.effect_history),
            "rng_state": context.rng.getstate(),
            "trigger_counts": dict(context.trigger_counts),
            "support_window": dict(context.support_window),
            "battle_trigger_counts": dict(context.battle_trigger_counts),
            "chain_counts": dict(context.chain_counts),
            "chain_exhausted": set(context.chain_exhausted),
            "chain_source_counts": dict(context.chain_source_counts),
            "chain_pending": list(context.chain_pending),
            "chain_queued": set(context.chain_queued),
            "battle_rule_serial": context.battle_rule_serial,
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
                    # 事实表按**一层浅拷**：事实里的键是就地替换的（`facts["当前数值"] = …`），
                    # 值本身没有原地改的写法；深拷事件栈是这份回滚点里最贵的一块（一次尝试
                    # 少则几层、多则上百层）。这一条用 A/B 逐事件对照与十条语料通道把关。
                    "facts": dict(frame.facts),
                    "tags": set(frame.tags),
                    "cancelled": frame.cancelled,
                    "transformed_kind": frame.transformed_kind,
                    "original_kind": frame.original_kind,
                }
                for frame in context.event_stack
            ],
            "summon_serial": context.summon_serial,
        }

    #: 回滚点里按「拷一层」处理的字典字段（值多半是标量或改不动的映射）。
    _SNAPSHOT_DICTS = (
        "attributes",
        "cooldowns",
        "inventory",
        "consumed_items",
        "forms",
        "form_modifiers",
        "five_elements",
        "battle_profile",
        "team_synergy",
    )
    #: 回滚点里按「列表浅拷」处理的字段。
    _SNAPSHOT_LISTS = ("passives", "tactic")
    _SNAPSHOT_CONTAINERS = frozenset((*_SNAPSHOT_DICTS, *_SNAPSHOT_LISTS,
                                    "statuses", "skills", "base_form_skills", "tags", "rules"))
    _SNAPSHOT_SCALAR_FIELDS = tuple(filterfalse(
        (_SNAPSHOT_CONTAINERS | {"rules_cache"}).__contains__, Fighter.__slots__
    ))
    _SNAPSHOT_SCALAR_GETTER = attrgetter(*_SNAPSHOT_SCALAR_FIELDS)

    @staticmethod
    def _snapshot_instances(values: Iterable[Skill | StatusState]) -> list[tuple[type, dict[str, Any]]]:
        # 快照只需要字段状态，无须先制造几千个临时 Skill/StatusState 对象。
        # 保留类型与独立字段表，真正回滚时才重建对象；字段的浅拷语义不变。
        return [value.snapshot_state() for value in values]

    @staticmethod
    def _restore_instances(values: Iterable[tuple[type, dict[str, Any]]]) -> list[Any]:
        restored = []
        for kind, state in values:
            value = kind.__new__(kind)
            value.__dict__.update(state)
            restored.append(value)
        return restored

    @staticmethod
    def _snapshot_fighter(fighter: Fighter) -> dict[str, Any]:
        if type(fighter) is Fighter:
            # 固定字段批量读取；大多数尝试成功，不必在每份快照上逐字段筛类型。
            # 恢复时仍跳过原来的可变值。规则缓存通常是字典，不额外保留它。
            scalars = dict(zip(AbilityRuntime._SNAPSHOT_SCALAR_FIELDS,
                               AbilityRuntime._SNAPSHOT_SCALAR_GETTER(fighter)))
            if not isinstance(fighter.rules_cache, (dict, list, set)):
                scalars['rules_cache'] = fighter.rules_cache
            scalars.update({key: value for key, value in fighter.__dict__.items()
                            if key not in AbilityRuntime._SNAPSHOT_CONTAINERS
                            and not isinstance(value, (dict, list, set))})
        else:
            # 扩展子类可能自定义属性读取，保留原读取顺序和筛选行为。
            scalars = {
                key: value
                for key, value in chain(
                    ((key, getattr(fighter, key)) for key in Fighter.__slots__),
                    fighter.__dict__.items(),
                )
                if key not in AbilityRuntime._SNAPSHOT_CONTAINERS
                and not isinstance(value, (dict, list, set))
            }
        return {
            "scalars": scalars,
            "dicts": {
                key: dict(getattr(fighter, key))
                for key in AbilityRuntime._SNAPSHOT_DICTS
            },
            "lists": {key: list(getattr(fighter, key)) for key in AbilityRuntime._SNAPSHOT_LISTS},
            "tags": set(fighter.tags),
            "statuses": AbilityRuntime._snapshot_instances(fighter.statuses),
            "skills": AbilityRuntime._snapshot_instances(fighter.skills),
            "base_form_skills": (
                None
                if fighter.base_form_skills is None
                else AbilityRuntime._snapshot_instances(fighter.base_form_skills)
            ),
        }

    @staticmethod
    def _restore_fighter(fighter: Fighter, snapshot: Mapping[str, Any]) -> None:
        for key, value in snapshot["scalars"].items():
            if not isinstance(value, (dict, list, set)):
                setattr(fighter, key, value)
        for key, value in snapshot["dicts"].items():
            setattr(fighter, key, dict(value))
        for key, value in snapshot["lists"].items():
            setattr(fighter, key, list(value))
        fighter.tags = set(snapshot["tags"])
        fighter.statuses = AbilityRuntime._restore_instances(snapshot["statuses"])
        fighter.skills = AbilityRuntime._restore_instances(snapshot["skills"])
        fighter.base_form_skills = (
            None
            if snapshot["base_form_skills"] is None
            else AbilityRuntime._restore_instances(snapshot["base_form_skills"])
        )

    @staticmethod
    def _restore_transaction(context: BattleContext, snapshot: Mapping[str, Any]) -> None:
        current = {fighter.id: fighter for fighter in context.fighters}
        for fighter_id, values in snapshot["fighters"].items():
            fighter = current.get(fighter_id)
            if fighter is None:
                continue
            AbilityRuntime._restore_fighter(fighter, values)
        context.left_team[:] = [current[value] for value in snapshot["left_ids"] if value in current]
        context.right_team[:] = [current[value] for value in snapshot["right_ids"] if value in current]
        context.rebuild_indexes()
        context.records = copy.deepcopy(snapshot["records"])
        context.relations = copy.deepcopy(snapshot["relations"])
        context.combat_objects = copy.deepcopy(snapshot["objects"])
        context.battle_rules = copy.deepcopy(snapshot["rules"])
        context.mark_listener_index_dirty()
        context.action_progress = dict(snapshot["progress"])
        context.ability_counters = dict(snapshot["counters"])
        context.saved_results = copy.deepcopy(snapshot["saved"])
        context.event_count = snapshot["event_count"]
        del context.events[snapshot["captured_event_count"]:]
        context.effect_history[:] = snapshot["effect_history"]
        context.rng.setstate(snapshot["rng_state"])
        context.trigger_counts = dict(snapshot["trigger_counts"])
        context.support_window = dict(snapshot["support_window"])
        context.battle_trigger_counts = dict(snapshot["battle_trigger_counts"])
        context.chain_counts = dict(snapshot["chain_counts"])
        context.chain_exhausted = set(snapshot["chain_exhausted"])
        context.chain_source_counts = dict(snapshot["chain_source_counts"])
        context.chain_pending = list(snapshot["chain_pending"])
        context.chain_queued = set(snapshot["chain_queued"])
        context.battle_rule_serial = snapshot["battle_rule_serial"]
        context.judgement_overrides = copy.deepcopy(snapshot["judgement_overrides"])
        context.action_intent = copy.deepcopy(snapshot["action_intent"])
        context.last_result = copy.deepcopy(snapshot["last_result"])
        context.triggered_skill_depth = snapshot["triggered_skill_depth"]
        context.summon_serial = snapshot["summon_serial"]
        # 回滚会换掉身上的状态（规则表缓存的依据），版本号推一格让缓存整体作废。
        context.status_rules_version = int(getattr(context, "status_rules_version", 0)) + 1
        for saved in snapshot["frames"]:
            frame = saved["frame"]
            for key in ("kind", "source", "target", "cancelled", "transformed_kind", "original_kind"):
                setattr(frame, key, saved[key])
            frame.facts = dict(saved["facts"])
            frame.tags = set(saved["tags"])

    @staticmethod
    def _ability_listener(*_args, **_kwargs) -> bool:
        return True

    def _mark_listeners_dirty_for_status(self, context: BattleContext, status: StatusState) -> None:
        """状态上的监听与锁定技都跟着状态生灭：在这里统一把版本号推一格。

        - 监听：只有真挂了 `监听` 的状态才需要重编监听表（没有监听的状态对表没有贡献）；
        - 锁定技：只有状态携带规则才推一格；无规则状态不改变规则集合。
          回滚会替换状态对象，因此仍整体作废规则缓存。
        """

        if status.rules:
            context.status_rules_version = int(getattr(context, "status_rules_version", 0)) + 1
        if status.listeners:
            context.mark_listener_index_dirty()

    def _compiled_listeners(self, context: BattleContext) -> dict[str, tuple]:
        """Compile listeners by event for the current structural battle state.

        除了「事件 → 监听列表」那张排好序的表，还建一张**分桶表**：按
        `(观察角色, 阵营关系)` 分，再按「同侧 / 对侧」预先并好。派发时就不用把整张表
        问一遍——「自身」的监听只可能在当事人身上，「己方 / 敌方」的只可能在本方 /
        对方那几位身上；每一桶里**谁和谁同侧**在装配期就定了，所以按侧并一次就够，
        不必每次派发再逐个持有者比一遍阵营。

        分桶表：`事件名 -> [(观察角色, 阵营关系, 取法)]`，取法是一个字典，键是
        「按谁取」——`自身` 那类键是持有者编号，其余键是阵营，`None` 键是「全给」
        （角色认不出来时的兜底，宁可多问、不许漏问）。
        """

        if not context.listener_index_dirty:
            return context.listener_index
        sink = _ListenerSink(
            engine=self,
            order=tuple(self.catalog.timing["事件监听"]["排序"]),
            participant_order=context.listener_fighter_order,
            participant_order_fallback=(2, 0),
        )
        self._collect_fighter_listeners(context, sink)
        self._collect_field_listeners(context, sink)
        self._collect_object_listeners(context, sink)
        self._collect_rule_listeners(context, sink)
        ordered = {
            event_name: tuple(sorted(values, key=lambda item: item[0]))
            for event_name, values in sink.grouped.items()
        }
        membership = tuple((id(fighter), fighter.id, fighter.side) for fighter in context.fighters)
        previous_index = context.listener_index
        unchanged = set()
        previous_membership = context.listener_membership
        # 仅新增单位且已有单位的身份/阵营不变时，未变的监听仍可复用。
        # 新增阵营会改变敌方分桶，成员移除、换阵营也必须重新建立路由。
        if previous_membership == membership or (
            previous_membership
            and set(previous_membership) <= set(membership)
            and {row[2] for row in previous_membership} == {row[2] for row in membership}
        ):
            for kind, entries in ordered.items():
                previous = previous_index.get(kind, ())
                if len(previous) == len(entries) and all(a is b for a, b in zip(previous, entries)):
                    unchanged.add(kind)
        context.listener_membership = membership
        context.listener_index = ordered
        context.listener_max_levels = {
            event: max(entry[14] for entry in entries) for event, entries in ordered.items()
        }
        # 布局一处定义、重建后逐条核（规矩 ⑥）：新加的字段若只加在造的一侧、忘了读的一侧，
        # 这里就会当场抛错，而不是静默按错位的下标读下去。
        _validate_listener_entries(ordered)
        # 兜底再推一格：真正换表也算一次作废（作废点一律走 `mark_listener_index_dirty`，
        # 这里只是防「有人直接置脏」——多推一格只慢不错）。
        context.listener_table_version += 1
        context.listener_buckets = {kind: buckets for kind, buckets in context.listener_buckets.items() if kind in unchanged}
        context.listener_roles = {kind: roles for kind, roles in context.listener_roles.items() if kind in unchanged}
        previous_cache = context.listener_candidate_cache
        retained = {"table": ordered}
        if previous_cache.get("table") is previous_index:
            for key, hit in previous_cache.items():
                if isinstance(key, tuple) and key[0] in unchanged:
                    # 未使用的候选无需重造；首次命中时再复制并刷新版本。
                    retained[key] = hit
        context.listener_candidate_cache = retained
        context.listener_index_dirty = False
        return context.listener_index

    def _event_listener_buckets(self, context: BattleContext, event_name: str) -> tuple:
        cached = context.listener_buckets.get(event_name)
        if cached is not None:
            return cached
        entries = context.listener_index.get(event_name)
        if not entries:
            context.listener_buckets[event_name] = ()
            return ()
        sides = tuple(dict.fromkeys(fighter.side for fighter in context.fighters))
        grouped: dict[tuple[str, str], dict[Any, list[tuple[int, Any]]]] = {}
        # 「自身」那一组的取法键是持有者编号，编号要到条目上才知道，所以它那份
        # 「全给」先寄在这儿，收完再挂到最后一位（与原先 `{**by_owner, None: …}` 同序）。
        self_full: dict[tuple[str, str], list[tuple[int, Any]]] = {}
        for position, entry in enumerate(entries):
            node = entry[6]
            role = str(node.get("观察角色") or "来源")
            relation = str(node.get("阵营关系") or "自身")
            key = (role, relation)
            slot = grouped.get(key)
            if slot is None:
                if relation == "自身":
                    slot = {}
                    self_full[key] = []
                elif relation in {"任意己方", "其他己方", "任意敌方"}:
                    slot = {None: []}
                    for side in sides:
                        slot[side] = []
                else:  # 任意（或不认识的关系）：全收，交给动态判定
                    slot = {None: []}
                grouped[key] = slot
            pair = (position, entry)
            owner = entry[1]
            if relation == "自身":
                self_full[key].append(pair)
                slot.setdefault(owner.id, []).append(pair)
            elif relation in {"任意己方", "其他己方"}:
                slot[None].append(pair)
                hits = slot.get(owner.side)
                if hits is not None:
                    hits.append(pair)
            elif relation == "任意敌方":
                slot[None].append(pair)
                for side in sides:
                    if side != owner.side:
                        hits = slot.get(side)
                        if hits is not None:
                            hits.append(pair)
            else:
                slot[None].append(pair)
        for key, full in self_full.items():
            grouped[key][None] = full
        result = [
            (role, relation, slot) for (role, relation), slot in grouped.items()
        ]
        context.listener_roles[event_name] = {
            role: any(r == role and relation in {'自身', '其他己方'} for r, relation in grouped)
            for role, _ in grouped
        }
        context.listener_buckets[event_name] = result
        return result

    def _event_parties(self, context: BattleContext, frame: EventFrame) -> dict[str, Any]:
        """事件里的「当事人」：观察角色 → 那个人。

        收窄候选与动态判定问的是同三个角色，所以**一次算好、两处共用**：动态判定
        原先每次自己造一份（百万次量级），而造它还要按行动者编号查一次人。
        """

        actor_id = str(frame.facts.get("行动者") or "")
        actor = (
            frame.source
            if not actor_id or actor_id == frame.source.id
            else context.fighter_by_id(actor_id) or frame.source
        )
        return {"来源": frame.source, "承受者": frame.target, "行动者": actor}

    def _listener_conditions_deterministic(self, conditions: Sequence[Mapping[str, Any]]) -> bool:
        """Whether skipping an already-capped listener's conditions preserves RNG state."""

        def visit(value: object) -> bool:
            if isinstance(value, Mapping):
                ability = value.get("能力")
                if ability is not None:
                    definition = self.catalog.abilities.get(str(ability))
                    if definition is None:
                        return False
                    executor = str(definition.get("执行器") or "")
                    if executor in {"概率条件", "随机数值"}:
                        return False
                return all(visit(item) for item in value.values())
            if isinstance(value, (list, tuple)):
                return all(visit(item) for item in value)
            return True

        return visit(conditions)

    def _listeners_for(self, context: BattleContext, kind: str, frame: EventFrame, parties: Mapping[str, Fighter] | None=None) -> list[tuple[int, Any]]:
        """这一条事件**真正需要问**的监听，带位次、顺序与整张排序表逐条一致。

        候选只按「阵营关系」收：自身 → 当事人一个；任意己方 / 其他己方 → 同侧那几位；
        任意敌方 → 对侧那几位；任意 → 全都给。收到的候选靠位次合并，**顺序与整张表
        一模一样**（同序是硬要求：结算先后决定结果）；真正的判定仍走动态那一步，
        所以这里只会「多给」，不会「漏给」。

        **位次要一起给出来**：事件目标会被 `修改事件目标` 一类效果中途改掉，改完得按
        位次补问「还没问过的那些」，所以调用方要知道每条监听在整张表里的位置。

        **候选表按「监听表 + 当事人」复用**（`context.listener_candidate_cache`）：这一问的
        答案只由两样东西决定——分桶表（跟整张排序表一起挂在 `context.listener_index` 上，
        重建时整个换成新对象）与「当事人」三位（来源 / 承受者 / 行动者）。同一张表下同一个
        签名问出来的候选表**逐条相同**（选取只查表、合并只按位次），所以整表复用与重算等价；
        调用方拿到的仍是同一份只读候选表（从不就地改它）。键里连**监听表对象**一起存，
        表一重建（`add_fighter` 入场 / 换阵营 / 状态进出 / 回滚）就整表作废；命中时**逐项核
        身份**——`Fighter` 不可哈希，键里放的是 `id()`，核过身份才敢用。

        **关系判定也一并做在缓存里**：这一问的答案除了分桶表与当事人，还要看
        `_listener_relation_matches`（它要读 `owner.side`），所以缓存的是**筛过**的候选表，
        并带上筛它时的监听表版本号（`_CandidateList.filtered_version`）。派发循环见到
        「版本没变」就跳过逐条判定；版本一变（换阵营会重建索引换表 → `listener_table_version`
        自增）就整体退回逐条判定。`_compiled_listeners` 在本方法开头已经跑过，所以这里拿到的
        版本号一定是这一趟的当前版本；没带这个戳的普通 `list` 一律按「未筛」处理。
        """

        if context.listener_index_dirty:
            self._compiled_listeners(context)
        version = context.listener_table_version
        if parties is None:
            parties = self._event_parties(context, frame)
        table = context.listener_index
        cache = context.listener_candidate_cache
        if cache.get("table") is not table:
            cache.clear()
            cache["table"] = table
        roles = context.listener_roles.get(kind)
        source_ref = parties.get("来源") if roles is None or "来源" in roles else None
        target_ref = parties.get("承受者") if roles is None or "承受者" in roles else None
        actor_ref = parties.get("行动者") if roles is None or "行动者" in roles else None
        if roles is not None:
            if source_ref is not None and not roles.get('来源'):
                source_ref = source_ref.side
            if target_ref is not None and not roles.get('承受者'):
                target_ref = target_ref.side
            if actor_ref is not None and not roles.get('行动者'):
                actor_ref = actor_ref.side
        key = (kind, id(source_ref), id(target_ref), id(actor_ref), context.chain_level)
        hit = cache.get(key)
        if (
            hit is not None
            and hit[0] is source_ref
            and hit[1] is target_ref
            and hit[2] is actor_ref
        ):
            pairs = hit[3]
            if isinstance(pairs, _CandidateList) and pairs.filtered_version != version:
                refreshed = _CandidateList(pairs, filtered_version=version)
                # 剩余候选只读共享；available 仍核对根链、行动和计数字典身份。
                refreshed.uncapped = pairs.uncapped
                refreshed.count_stamp = pairs.count_stamp
                cache[key] = (source_ref, target_ref, actor_ref, refreshed)
                pairs = refreshed
            return pairs
        buckets = self._event_listener_buckets(context, kind)
        if not buckets:
            return _CandidateList((), filtered_version=version)
        groups: list[list[tuple[int, Any]]] = []
        relations_known = True
        for role, relation, by_key in buckets:
            who = parties.get(role)
            if who is None:
                # 角色认不出来：全给，交给动态判定（宁可多问，不许漏问）。
                hits = by_key.get(None)
            elif relation == "自身":
                hits = by_key.get(who.id)
            elif relation in {"任意己方", "其他己方", "任意敌方"}:
                # 「敌方」那一桶的键也是**当事人自己的阵营**：装配时已经按「不是这侧的」
                # 并好了，所以这里与「己方」同一写法。
                hits = by_key.get(who.side)
            else:  # 任意（或不认识的关系）：全收
                hits = by_key.get(None)
            if hits:
                if who is None or relation not in {"自身", "任意己方", "其他己方", "任意敌方", "任意"}:
                    relations_known = False
                elif relation == "自身":
                    hits = [pair for pair in hits if pair[1][1] is who]
                elif relation == "其他己方":
                    hits = [pair for pair in hits if pair[1][1] is not who]
                groups.append(hits)
        if not groups:
            filtered = _CandidateList((), filtered_version=version)
            cache[key] = (source_ref, target_ref, actor_ref, filtered)
            return filtered
        if len(groups) == 1:
            pairs = groups[0]
        else:
            # 多桶合并：一趟 `sorted` 代替 `heapq.merge`。两者**必然同序**——位次是同一条事件
            # 排序表里的下标，每个条目恰好落进一个 `(观察角色, 阵营关系)` 分组、每个分组里恰好
            # 落进一个取法桶，所以各 `groups` 之间的位次**互不相同**，按位次排出来的序列是**唯一**的
            # （`heapq.merge` 那条「键相等时按迭代器先后」的稳定规则在这里根本用不上）。
            # 实测同一批真实候选（2,125 批 / 26,618 条，2~6 个桶）：单条 381.4 ns → 88.3 ns · 4.32×。
            pairs = sorted(chain.from_iterable(groups), key=_POSITION)
        # 判定要读 `owner.side`，而 `owner.side` 只有换阵营才会变、换阵营必然重排位次换表，
        # 所以拿当前版本号封一次「已筛」戳是成立的（见 `_CandidateList`）。
        #
        # **判不出来就一条不筛**：`_listener_relation_matches` 对认不出的角色 / 关系是抛错，
        # 而抛错在原先发生在**派发循环轮到它那一条时**（前面几条的效果已经跑过了）。筛在这里
        # 会把抛错提到循环之前，那就不是「等价改慢」而是改了行为——所以这里一旦抛错，整表退回
        # 未筛（普通 `list`），让循环照原样逐条问、照原样在原来的位置抛。
        # 阵营关系已经由桶选择完成；只需在桶内处理身份排除。未知关系仍交还
        # 派发循环，在原来的监听位置报错，不能提前执行或漏执行前面的监听。
        if not relations_known:
            fallback = list(pairs)
            cache[key] = (source_ref, target_ref, actor_ref, fallback)
            return fallback
        # 响应等级由声明决定，同一派发中执行子链后总会恢复原等级。
        # 在缓存建立时按等级收窄，省去每次派发扫描永久不具资格的条目。
        level = context.chain_level
        if level > 1:
            pairs = [pair for pair in pairs if (
                pair[1][14] if len(pair[1]) > 14 else response_level(pair[1][6])
            ) >= level]
        filtered = _CandidateList(pairs, filtered_version=version)
        cache[key] = (source_ref, target_ref, actor_ref, filtered)
        return filtered

    def _collect_fighter_listeners(self, context: BattleContext, sink: _ListenerSink) -> None:
        """修士自带的监听：被动槽位在前，状态（战丹、长期伤势）在后。

        两者留在同一个循环里是有意的：键值完全相同的那两条，最终靠稳定排序保持这个
        先后；拆成两遍遍历修士就会把次序换掉。

        **被动那一段是按持有者缓存的纯静态段**（见 `_passive_listener_entries`）：回放
        仍发生在「这一位修士的被动位置」上——即同一循环里状态之前，所以「被动在前、
        状态在后」的先后、连同键值相同的那些的先后，都与原先逐条现收一致。
        """

        passive_signature = tuple(
            (owner.id, owner, tuple(owner.passives), context.listener_fighter_order.get(owner.id, (2, 0)))
            for owner in context.fighters
        )
        cached_passives = context.listener_passive_index
        if (
            cached_passives is None
            or len(cached_passives) != len(passive_signature)
            or any(
                cached_passives[index][0] != owner.id
                or context.fighter_by_id(cached_passives[index][0]) is not owner
                or len(cached_passives[index][2]) != len(passives)
                or any(a is not b for a, b in zip(cached_passives[index][2], passives))
                or cached_passives[index][3] != order
                for index, (owner_id, owner, passives, order) in enumerate(passive_signature)
            )
        ):
            cached_passives = tuple(
                (owner.id, self._passive_listener_entries(context, owner), tuple(owner.passives), context.listener_fighter_order.get(owner.id, (2, 0)))
                for owner in context.fighters
            )
            context.listener_passive_index = cached_passives
        for owner_id, passive_entries, _passives, _order in cached_passives:
            owner = context.fighter_by_id(owner_id)
            for event_name, values in passive_entries.items():
                sink.grouped.setdefault(event_name, []).extend(values)
            for status in owner.statuses:
                if not status.listeners:
                    continue
                item_id = str(status.values.get("战丹编号") or status.name)
                for index, node in enumerate(status.listeners):
                    sink.add(
                        owner,
                        f"{status.name}:{index}",
                        node,
                        source_ability=status.source_ability or status.name,
                        item_id=item_id,
                        ability_order=index,
                        source_category="战丹",
                        build_instance=str(status.build_instance or ""),
                    )

    def _passive_listener_entries(self, context: BattleContext, owner: Fighter) -> Mapping[str, tuple]:
        """修士**被动**那一段编译好的监听条目（纯静态段，按持有者缓存在场上）。

        为什么这一段是纯静态的：每一条只由两样东西决定，而这两样在一场战斗里都不再变——
        ①`owner.passives` 里那份**装配期**写死的被动表（`_assemble_passive_skill` 生成，
        条目字段 `监听键` / `结算顺序` / `装配位序` / `物品编号` / `能力序号` / `效果序号` /
        `来源类别` / `构筑实例` / `属性构成` / `节点` 全在里面）；②`owner` 在
        `context.listener_fighter_order` 里的队伍/队内位次。派生量（排序键、名额键、条目元组）只额外依赖
        `engine._source_layers` 与 `catalog.timing`（第 2 步起的装配期常量）。
        这一段在一场里被现收 30~60 遍，每遍 2,800 条上下（实测 99.8% 的
        `_ListenerSink.add` 调用出自它），而内容一遍都没变。

        失效判据只有**持有者同一**（缓存里连持有者对象一起存）＋**被动表逐项同一**（长度不等
        即不命中；回滚走 `_restore_fighter`，把被动表原样拷回、装着同一批 dict 对象，所以回滚后
        照旧命中）。位次**不算失效**：位次只是排序键的第四项，而条目里其余的键与值全是被动表与
        装配期常量的纯函数，所以位次一变只需按位次重拼一遍键（见下面那段）。实测九成的不命中
        都是「只有位次变了」——`add_fighter`（战斗对象入场）与 `_restore_transaction`（回滚）
        都会 `rebuild_indexes()` 重排位次。如今使用与全局位次同序的队伍/队内位次，
        己方追加召唤物不再改变敌方键；队内插入、移除或重排仍会使受影响的键失效。

        回放：调用方按事件把条目**按原顺序**并进同一张 sink 的同一位置，所以稳定排序的
        先后与逐条现收完全一致。本段之外的动态段（状态监听、战场环境、战斗对象、战场
        规则）一律照旧现收——它们各自会在战斗中变化（状态生灭、环境换阶、对象进出、
        规则增删），不是纯静态。
        """

        cached = context.listener_passive_cache.get(owner.id)
        order = context.listener_fighter_order.get(owner.id, (2, 0))
        passives = owner.passives
        stamp = tuple(passives)
        # 命中要的是**同一批对象**：持有者身份 + 被动表逐项同一（长度不等即不命中）。
        # 值相等不等于同一批：编号复用时会误命中，把条目挂在已经不在场上的旧持有者身上。
        if (
            cached is not None
            and cached[0] is owner
            and len(cached[1]) == len(stamp)
            and all(a is b for a, b in zip(cached[1], stamp))
        ):
            if cached[2] == order:
                return cached[3]
            # **只有位次变了**：位次只是排序键里的一位（下标见
            # `_ListenerSink.PARTICIPANT_ORDER_INDEX`，由 `foundation.EVENT_LISTENER_SORT_ORDER`
            # 算出），条目里其余的键与值全是「被动表 + 装配期常量」的纯函数（同一批被动对象、
            # 同一 `_source_layers`、同一 `catalog.timing`），输入一个字没动，所以按位次重拼一遍
            # 键即可，不必走 `add` 那一路把每条监听从头再造（取值、类型转换、`节点` 浅拷、
            # 名额键拼串都白做）。实测量到的**九成不命中**都是这一类。
            index = _ListenerSink.PARTICIPANT_ORDER_INDEX
            entries = {
                event_name: tuple(
                    (entry[0][:index] + (order,) + entry[0][index + 1 :],) + entry[1:]
                    for entry in values
                )
                for event_name, values in cached[3].items()
            }
            context.listener_passive_cache[owner.id] = (owner, cached[1], order, entries)
            return entries
        sink = _ListenerSink(
            engine=self,
            order=tuple(self.catalog.timing["事件监听"]["排序"]),
            participant_order=context.listener_fighter_order,
            participant_order_fallback=(2, 0),
        )
        for passive in passives:
            for mechanism_id, node in self._passive_listener_nodes(passive):
                sink.add(
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
        entries = {event_name: tuple(values) for event_name, values in sink.grouped.items()}
        context.listener_passive_cache[owner.id] = (owner, stamp, order, entries)
        return entries

    def _collect_field_listeners(self, context: BattleContext, sink: _ListenerSink) -> None:
        """战场环境本阶的常驻监听。"""

        if context.field is None:
            return
        field = context.field
        for index, node in enumerate(field.stage.passive_abilities):
            sink.add(
                field.source,
                f"环境:{field.definition.environment_id}:{field.stage_index}:{index}",
                node,
                source_ability=field.stage.name,
                settlement_order=0,
                item_id=f"环境:{field.definition.environment_id}",
                ability_order=index,
                source_category="战场环境",
            )

    def _collect_object_listeners(self, context: BattleContext, sink: _ListenerSink) -> None:
        """战斗对象（召唤物一类）自己的监听；已失效的不收。"""

        for obj in context.combat_objects.values():
            if not obj.active:
                continue
            owner = context.fighter_by_id(obj.owner_id) or context.left
            for index, node in enumerate(obj.listeners):
                sink.add(
                    owner,
                    f"{obj.id}:{index}",
                    node,
                    source_ability=obj.name,
                    item_id=obj.id,
                    ability_order=index,
                    source_category="战斗对象",
                )

    def _collect_rule_listeners(self, context: BattleContext, sink: _ListenerSink) -> None:
        """战场规则声明的监听，归属写明的来源修士。"""

        for index, rule in enumerate(context.battle_rules):
            if "运行编号" not in rule:
                context.battle_rule_serial += 1
                rule["运行编号"] = context.battle_rule_serial
            identity = rule["运行编号"]
            owner = context.fighter_by_id(str(rule.get("来源") or "")) or context.left
            for listener_index, node in enumerate(rule.get("监听") or ()):
                sink.add(
                    owner,
                    f"战场:{identity}:{listener_index}",
                    node,
                    source_ability=str(rule.get("名称") or "战场规则"),
                    item_id=f"战场:{identity}",
                    ability_order=listener_index,
                    source_category="战场规则",
                    build_instance=str(rule.get("构筑实例") or ""),
                )

    def _source_layer(self, source: str) -> int:
        """来源类别 → 层级序位。

        `时序.来源层级` 是**装配期的静态内容**（启动期校验过：来源非空且不重复、序位是
        非负且不重复的整数），一场战斗里一个字都不会变；而这里一场要被问 10 万次
        （`_ListenerSink.add` 每收一条监听问一次、`_skill_order_key` 每次排技能问一次）。
        所以 `BattleEngine.__init__` 已在装配期把整张表摊成「来源 → 序位」
        （`_source_layers`），这里只查一次字典；取值与原先逐条扫描**逐字相同**：
        同样是拿 `str(source)` 去比、同样只认**第一条**命中的来源（见 `_source_layers`），
        未登记时同样报 `ValueError`。
        """

        layer_order = self._source_layers.get(str(source))
        if layer_order is None:
            raise ValueError(f"战斗时序未登记来源层级：{source}")
        return layer_order

    def _dispatch_event(self, context: BattleContext, *, kind: str, source: Fighter, target: Fighter, amount: float=0.0, values: Mapping[str, Any] | None=None, tags: Iterable[str]=(), record: bool=True, capture: bool=True) -> EventFrame:
        if context.chain_active:
            return self._dispatch_event_body(context, kind=kind, source=source, target=target,
                                             amount=amount, values=values, tags=tags, record=record, capture=capture)
        with self.root_chain(context):
            return self._dispatch_event_body(context, kind=kind, source=source, target=target,
                                             amount=amount, values=values, tags=tags, record=record, capture=capture)

    def _dispatch_event_body(self, context: BattleContext, *, kind: str, source: Fighter, target: Fighter, amount: float=0.0, values: Mapping[str, Any] | None=None, tags: Iterable[str]=(), record: bool=True, capture: bool=True, chain_entry: tuple | None=None) -> EventFrame:
        depth_limit = self._event_depth_limit
        # 到顶之后**这次事件照旧发生、照旧进战报，只是不再往下触发监听**——见
        # `data/战斗/规则/说明.md` 的「两条链的上限」。留痕：事实里记 `链深度跳过`。
        over_depth = context.event_depth >= depth_limit
        if str(kind) not in self._event_names:
            raise ValueError(f"战斗核心未登记事件：{kind}")
        facts = dict(values or {})
        facts.setdefault('事件', kind)
        facts.setdefault('来源', source.id)
        facts.setdefault('承受者', target.id)
        facts.setdefault('行动者', source.id)
        facts.setdefault('原始数值', float(amount))
        facts.setdefault('当前数值', float(amount))
        facts['根链'] = context.chain_serial
        facts['响应来源等级'] = context.chain_level
        if over_depth:
            facts['链深度跳过'] = True
        frame = EventFrame(kind, source, target, facts, set(tags))
        if context.listener_index_dirty:
            self._compiled_listeners(context)
        event_listeners = context.listener_index.get(kind)
        # 当前等级高于全部监听时没有任何回调能运行，故可使用原有空事件路径。
        # 显式链尾条目与深度越界仍走原路径；未编译的测试表保守按最高等级处理。
        if not over_depth and chain_entry is None and (
            not event_listeners or context.listener_max_levels.get(kind, 3) < context.chain_level
        ):
            if record:
                context.event_count += 1
                if capture and (context.event_capture_filter is None or kind not in context.event_capture_filter) and not (
                    kind in context.event_capture_zero_change_kinds
                    and frame.amount == 0
                    and "变化前数值" in frame.facts
                    and frame.facts["变化前数值"] == frame.facts.get("变化后数值")
                ):
                    context.events.append(BattleEvent(
                        turn=context.action_number, kind=kind, source=source.name,
                        target=target.name, text=kind, amount=round(frame.amount, 3),
                        values=record_values(self.recorded_facts, frame.facts),
                        tags=tuple(sorted(frame.tags)), ability=context.current_ability,
                        source_id=source.id, target_id=target.id,
                    ))
            return frame
        # 候选完全为空时，这条事件只需保留事实与战报。此时没有任何监听能改写
        # 目标、标签或数值，也没有子事件；先筛候选再压入事件栈，省掉空派发的栈操作。
        parties = self._event_parties(context, frame)
        if over_depth:
            pairs = []
        else:
            # 事件类型若没有任何监听，候选缓存、关系筛选和排序都没有意义；
            # 仍创建并记录事件，只跳过空调度链。监听表本身由静态/动态索引统一提供，
            # 因此不会漏掉运行时新增的状态监听。
            pairs = (
                self._listeners_for(context, kind, frame, parties)
                if event_listeners
                else []
            )
        # 候选表若已按关系筛过、且监听表版本没变，逐条 `_listener_relation_matches` 就白问
        # （唯一会变的输入是 `owner.side`，换阵营必重建索引换表 → 版本自增）。
        # 版本对不上（真的换过表）就退回逐条判定，语义与从前一致。
        filtered_version = getattr(pairs, "filtered_version", None)
        if filtered_version == context.listener_table_version:
            pairs = pairs.available(context)
        if chain_entry is not None:
            pairs = [(0, chain_entry)]
            filtered_version = None
        if not pairs:
            if record:
                context.event_count += 1
                if capture and (
                    context.event_capture_filter is None
                    or kind not in context.event_capture_filter
                ) and not (
                    kind in context.event_capture_zero_change_kinds
                    and frame.amount == 0
                    and "变化前数值" in frame.facts
                    and frame.facts["变化前数值"] == frame.facts.get("变化后数值")
                ):
                    context.events.append(
                        BattleEvent(
                            turn=context.action_number,
                            kind=kind,
                            source=source.name,
                            target=target.name,
                            text=kind,
                            amount=round(frame.amount, 3),
                            values=record_values(self.recorded_facts, frame.facts),
                            tags=tuple(sorted(frame.tags)),
                            ability=context.current_ability,
                            source_id=source.id,
                            target_id=target.id,
                        )
                    )
            return frame
        context.event_stack.append(frame)
        context.event_depth += 1
        try:
            # 候选集按「事件当下的当事人」收窄。但监听效果里可能改写事件目标；目标一变
            # 就重算候选，只补跑位次在后面的条目，维持原始排序与既有语义。
            narrowed_target = frame.target
            event_tags = tuple(frame.tags)
            # 普通派发直接迭代候选；只有目标改写时才从新候选表的后续位次继续。
            rescan = True
            while rescan:
                rescan = False
                for position, entry in pairs:
                    if len(entry) == _LISTENER_ENTRY_LEN:
                        level = entry[14]
                        if level < context.chain_level:
                            continue
                        chain_limit = entry[15]
                        activation = entry[13]
                        if chain_limit:
                            if chain_limit == 1:
                                if activation in context.chain_exhausted:
                                    continue
                            elif context.chain_counts.get(activation, 0) >= chain_limit:
                                continue
                        (_, owner, activation_id, _activation_budget, source_ability,
                         build_instance, node, composition, conditions, per_action,
                         per_battle, effects, deterministic_conditions, activation,
                         level, chain_limit, settlement_phase, source_chain_limit) = entry
                    else:
                        (_, owner, activation_id, _activation_budget, source_ability,
                         build_instance, node, composition, conditions, per_action,
                         per_battle, effects, deterministic_conditions, activation) = entry
                        level = response_level(node)
                        chain_limit = int(node.get("每条根链最多触发", 1) or 0)
                        settlement_phase = str(node.get("结算阶段") or "")
                        source_chain_limit = int(node.get("同一事件来源每条根链最多触发", 0) or 0)
                        if level < context.chain_level:
                            continue
                        if chain_limit:
                            if chain_limit == 1:
                                if activation in context.chain_exhausted:
                                    continue
                            elif context.chain_counts.get(activation, 0) >= chain_limit:
                                continue
                    source_budget_key = None
                    if source_chain_limit:
                        source_budget_key = (activation, frame.source.id)
                        if context.chain_source_counts.get(source_budget_key, 0) >= source_chain_limit:
                            continue
                    support_limit = int(node.get("自身行动间隔最多触发", 0) or 0)
                    if support_limit:
                        support_key = activation
                        if context.support_window.get(support_key, 0) >= support_limit:
                            continue
                    if (
                        filtered_version is None
                        or filtered_version != context.listener_table_version
                    ) and not self._listener_relation_matches(owner, node, parties):
                        continue
                    if settlement_phase == "链尾" and chain_entry is None:
                        if activation not in context.chain_queued:
                            context.chain_queued.add(activation)
                            context.chain_pending.append((entry, kind, source.id, frame.target.id,
                                                          frame.amount, dict(frame.facts), event_tags))
                        continue
                    # 名额按（修士, 词条, 声明）算，不按卡的第几张算。
                    if deterministic_conditions:
                        if activation in context.trigger_stack:
                            continue
                        if per_action and context.trigger_counts.get(activation, 0) >= per_action:
                            continue
                        if per_battle and context.battle_trigger_counts.get(activation, 0) >= per_battle:
                            continue
                    if conditions:
                        # 条件中的构筑计量属于这条监听，而非派发事件的上一条能力。
                        # 与下方效果执行使用同一作用域；异常也必须还原外层作用域。
                        previous_condition_instance = context.current_build_instance
                        context.current_build_instance = build_instance
                        try:
                            allowed = self._conditions_allow(
                                context, owner, frame.target, conditions, frame.amount, frame.facts, event_tags
                            )
                        finally:
                            context.current_build_instance = previous_condition_instance
                        if not allowed:
                            continue
                    if not deterministic_conditions:
                        if activation in context.trigger_stack:
                            continue
                        if per_action and context.trigger_counts.get(activation, 0) >= per_action:
                            continue
                        if per_battle and context.battle_trigger_counts.get(activation, 0) >= per_battle:
                            continue
                    action_count = context.trigger_counts.get(activation, 0)
                    battle_count = context.battle_trigger_counts.get(activation, 0)
                    previous_chain_count = context.chain_counts.get(activation, 0)
                    context.trigger_counts[activation] = action_count + 1
                    context.battle_trigger_counts[activation] = battle_count + 1
                    if support_limit:
                        support_count = context.support_window.get(support_key, 0) + 1
                        context.support_window[support_key] = support_count
                        if support_count == support_limit:
                            context.listener_budget_version += 1
                    chain_count = previous_chain_count + 1
                    context.chain_counts[activation] = chain_count
                    # 候选表只需在某条监听刚刚耗尽名额时重筛。名额尚有剩余时，
                    # 计数虽增加，但候选资格没有变化；逐次递增会让每个嵌套事件都重扫整张表。
                    if (
                        chain_limit and previous_chain_count < chain_limit <= chain_count
                        or deterministic_conditions and (
                            per_action and action_count < per_action <= action_count + 1
                            or per_battle and battle_count < per_battle <= battle_count + 1
                        )
                    ):
                        context.listener_budget_version += 1
                    if chain_limit and chain_count >= chain_limit:
                        context.chain_exhausted.add(activation)
                    if source_chain_limit:
                        context.chain_source_counts[source_budget_key] = (
                            context.chain_source_counts.get(source_budget_key, 0) + 1
                        )
                    context.trigger_stack.add(activation)
                    previous = context.current_ability
                    previous_composition = context.current_element_composition
                    previous_instance = context.current_build_instance
                    previous_level = context.chain_level
                    context.chain_level = level
                    context.current_ability = source_ability
                    context.current_build_instance = build_instance
                    context.current_element_composition = dict(composition)
                    try:
                        self._run_effects(
                            context,
                            owner,
                            frame.target,
                            effects,
                            1.0,
                            event_amount=frame.amount,
                            event_values=frame.facts,
                            tags=event_tags,
                        )
                    finally:
                        context.current_ability = previous
                        context.chain_level = previous_level
                        context.current_build_instance = previous_instance
                        context.current_element_composition = previous_composition
                        context.trigger_stack.discard(activation)
                    if frame.target is not narrowed_target and chain_entry is None:
                        narrowed_target = frame.target
                        parties = self._event_parties(context, frame)
                        pairs = self._listeners_for(context, kind, frame, parties)
                        # 补跑用的是新候选表：它的「已筛」戳也要跟着换（同一趟里版本可能已经变了）。
                        filtered_version = getattr(pairs, "filtered_version", None)
                        if filtered_version == context.listener_table_version:
                            pairs = pairs.available(context)
                        pairs = pairs[bisect.bisect_right(pairs, position, key=_POSITION):]
                        rescan = True
                        break
            # 转化目标若已经在结算栈上，这次转化没有意义——那等于重入一个正在结算
            # 的事件。此时**放弃转化**，让原事件按自己的语义继续结算。
            #
            # 之所以不抛错：成环不是单张卡的错，而是两张卡对向作用的结果
            # （例：己方「反哺」把敌方恢复转成护盾，那个护盾又引出一次恢复，
            # 被敌方的「反哺」再转成护盾）。「每次行动最多触发」是按监听实例
            # 算的，双方各一个实例就合法地触发两次，足够闭环。作者在本地看不到
            # 这个环，所以语义只能由引擎定；而定成「炸掉整场战斗」意味着
            # 带这套构筑的玩家每打一架都报错。
            # 跳过仍然留痕：`事实` 里记下被放弃的目标事件，便于事后审。
            if frame.transformed_kind and frame.transformed_kind in {
                item.kind for item in context.event_stack
            }:
                frame.facts["转化跳过"] = frame.transformed_kind
                frame.transformed_kind = None
            if frame.transformed_kind:
                frame.facts["原事件"] = frame.kind
                frame.facts["事件"] = frame.transformed_kind
            if record and not frame.transformed_kind:
                context.event_count += 1
                if capture and (
                    context.event_capture_filter is None
                    or frame.kind not in context.event_capture_filter
                ) and not (
                    frame.kind in context.event_capture_zero_change_kinds
                    and frame.amount == 0
                    and "变化前数值" in frame.facts
                    and frame.facts["变化前数值"] == frame.facts.get("变化后数值")
                ):
                    context.events.append(
                        BattleEvent(
                            turn=context.action_number,
                            kind=frame.transformed_kind or frame.kind,
                            source=frame.source.name,
                            target=frame.target.name,
                            text=frame.transformed_kind or frame.kind,
                            amount=round(frame.amount, 3),
                            values=record_values(self.recorded_facts, frame.facts),
                            tags=tuple(sorted(frame.tags)),
                            ability=context.current_ability,
                            source_id=frame.source.id,
                            target_id=frame.target.id,
                        )
                    )
            if frame.transformed_kind:
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

    def _listener_relation_matches(self, owner: Fighter, node: Mapping[str, Any], parties: Mapping[str, Any]) -> bool:
        """这条监听此刻该不该问：看它观察的角色与持有者的阵营关系。

        `parties` 由调用方一次算好（见 `_event_parties`）——事件目标中途被改时，
        调用方会重算它再重算候选，所以这里拿到的永远是**当下**的当事人。

        调用点有两处：派发循环逐候选问，以及 `_listeners_for` 建候选表时**整批**筛一遍
        （筛过的表带版本号戳，循环就不必再问）。两处判据完全相同——认不出的角色 / 关系一律
        抛 `ValueError`；`_listeners_for` 那一处**抛了就整表退回未筛**，好让抛错仍发生在
        循环轮到那一条的位置上（见那里的注释）。
        """

        role = str(node.get("观察角色") or "来源")
        observed = parties.get(role)
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

    def _conditions_allow(self, context: BattleContext | None, source: Fighter | None, target: Fighter | None, conditions: Sequence[Mapping[str, Any]], event_amount: float, event_values: Mapping[str, Any], tags: Iterable[str]) -> bool:
        """这一串条件是否**全部成立**；**空条件恒成立**。

        调用方**先看有没有条件再来问**（`_ability_conditional` / `_dispatch_event` /
        `_rules_denied_rule` 三处都是这个写法）：空条件时这次调用，连同三个实参的求值
        （`frame.amount` 是 property、`tuple(frame.tags)` 要现造元组、`dict(values or {})`
        要现拷一份）全都是白付的。实测一场 **21.7 万次调用里 80.6% 是空条件**——循环体一次都不进。
        所以「空条件返回真」在这里只是兜底，热路径不该走到它。

        加新的条件调用点时照这个写法抄：**先判空，再问**。
        """

        # 条件序列来自装配期冻结的内容，执行器只是它的**纯函数**（`parse_node` 自己就按节点
        # 身份缓存）。整批算一次、按序列身份缓存（核 `is` + 核长度兜底），省掉每个条件节点一次
        # `parse_node` 调用——实测这一处 **14,569 次 / 7.1 ms**。交给判定器的仍是自己那份拷贝。
        #
        # **`context` 可能是 `None`**：规则层有「没有战斗现场也问一遍条件」的用法（第 29 步
        # 第一次改时正是踩在这里：`AttributeError: 'NoneType' object has no attribute
        # 'condition_executor_cache'`，被 `tools/全量核对.py` 的「规则层行为」当场拦下）。
        # 没有 context 就没有地方存缓存，退回逐条现算——语义一字不差。
        plan = None
        if context is not None:
            cached = context.condition_executor_cache.get(id(conditions))
            if cached is None or cached[0] is not conditions or len(cached[1]) != len(conditions):
                cached = (conditions, self._compile_condition_sequence(conditions))
                context.condition_executor_cache[id(conditions)] = cached
            plan = cached[1]
        if plan is None:
            plan = self._compile_condition_sequence(conditions)
        return self._evaluate_condition_plan(
            context, source, target, plan, event_amount, event_values, tags
        )

    def _compile_condition_sequence(self, conditions: Sequence[Mapping[str, Any]]) -> tuple:
        return tuple(
            self._compile_condition_plan_item(raw, self.catalog.parse_node(raw).executor)
            for raw in conditions or ()
        )

    def _evaluate_condition_plan(self, context: BattleContext | None, source: Fighter | None, target: Fighter | None, plan: tuple, event_amount: float, event_values: Mapping[str, Any], tags: Iterable[str]) -> bool:
        for raw, handler, executor in plan:
            if raw is None:
                if not handler:
                    return False
                continue
            if handler is None:
                raise ValueError(f"战斗核心未实现条件执行器：{executor or '<空>'}")
            # 条件处理器只读字段；节点来自装配期冻结的 JSON，直接复用映射可省掉
            # 每个条件、每次监听触发的一次字典复制。
            if not handler(context, source, target, raw, event_amount, event_values, tags):
                return False
        return True

    def _compile_condition_plan_item(self, raw: Mapping[str, Any], executor: str) -> tuple:
        """编译一条条件；只折叠完全由字面量决定的数值条件。"""

        handler = self._condition_handlers.get(executor)
        if executor == "组合条件" and getattr(handler, '__func__', None) is AbilityRuntime._condition_combined:
            children = self._compile_condition_sequence(raw.get("条件") or ())
            relation = str(raw.get("关系") or "全部成立")

            def evaluate_combined(context: BattleContext, source: Fighter, target: Fighter, condition: Mapping[str, Any], amount: float, values: Mapping[str, Any], tags: Iterable[str]) -> bool:
                results = [
                    self._evaluate_condition_plan(
                        context, source, target, (child,), amount, values, tags
                    )
                    for child in children
                ]
                relation_value = str(condition.get("关系") or relation)
                if relation_value == "全部成立":
                    return all(results)
                if relation_value == "任一成立":
                    return any(results)
                if relation_value == "全部不成立":
                    return not any(results)
                raise ValueError(f"未知组合条件关系：{relation_value}")

            return (raw, evaluate_combined, executor)
        if executor == "数值条件" and getattr(handler, '__func__', None) is AbilityRuntime._condition_numeric:
            left = raw.get("左值")
            right = raw.get("右值")
            if type(left) in (int, float) and type(right) in (int, float):
                return (None, self._compare(float(left), float(right), str(raw.get("比较") or "等于")), executor)
            left_plan = self._compile_condition_value(left)
            right_plan = self._compile_condition_value(right)
            if left_plan is not None or right_plan is not None:
                relation = str(raw.get("比较") or "等于")
                # 字面量无需在每次判定时经过通用数值分派。动态一侧仍实时求值。
                if left_plan is not None and left_plan[0] == "常量":
                    constant = left_plan[1]
                    def evaluate_left(context: BattleContext, source: Fighter, target: Fighter, condition: Mapping[str, Any], amount: float, values: Mapping[str, Any], _tags: Iterable[str]) -> bool:
                        right_value = self._resolve_condition_value(
                            context, right_plan, right, source, target, amount, values
                        )
                        return self._compare(constant, right_value, relation)
                    return (raw, evaluate_left, executor)
                if right_plan is not None and right_plan[0] == "常量":
                    constant = right_plan[1]
                    def evaluate_right(context: BattleContext, source: Fighter, target: Fighter, condition: Mapping[str, Any], amount: float, values: Mapping[str, Any], _tags: Iterable[str]) -> bool:
                        left_value = self._resolve_condition_value(
                            context, left_plan, left, source, target, amount, values
                        )
                        return self._compare(left_value, constant, relation)
                    return (raw, evaluate_right, executor)
                def evaluate(context: BattleContext, source: Fighter, target: Fighter, condition: Mapping[str, Any], amount: float, values: Mapping[str, Any], _tags: Iterable[str]) -> bool:
                    left_value = self._resolve_condition_value(
                        context, left_plan, condition.get("左值"), source, target, amount, values
                    )
                    right_value = self._resolve_condition_value(
                        context, right_plan, condition.get("右值"), source, target, amount, values
                    )
                    return self._compare(
                        left_value, right_value, str(condition.get("比较") or "等于")
                    )

                return (raw, evaluate, executor)
        return (raw, handler, executor)

    def _compile_condition_value(self, value: Any) -> tuple | None:
        if type(value) in (int, float):
            return ("常量", float(value))
        if not isinstance(value, Mapping) or "能力" not in value:
            return None
        node = self.catalog.parse_node(value)
        if node.executor == "读取数值" and getattr(self._value_handlers.get(node.executor), '__func__', None) is AbilityRuntime._value_read:
            return ("读取数值", (node.values, self._compile_read_value(node.values)))
        return None

    def _resolve_condition_value(
        self, context: BattleContext | None, plan: tuple | None, raw: Any, source: Fighter | None, target: Fighter, amount: float, values: Mapping[str, Any]
    ) -> float:
        if plan is None:
            return self._resolve_value(context, raw, source, target, amount, values)
        kind, value = plan
        if kind == "常量":
            return value
        node, reader = value
        result = reader(context, source, target, node, amount, values)
        if type(result) is float:
            return result
        if isinstance(result, bool) or not isinstance(result, (int, float)):
            raise TypeError(f"战斗数值必须是数字：{result!r}")
        return float(result)

    def _compile_read_value(self, node: Mapping[str, Any]) -> Callable[..., Any]:
        """预绑定只读数值节点的字段；每次仍重新选目标、读取状态并求值。"""
        origin = str(node.get("来源") or "固定值")
        if origin not in {"固定值", "自身属性", "效果来源属性", "目标属性", "事件事实", "本次数值", "构筑计量", "状态层数", "行动条"}:
            return self._value_read
        selector = node.get("目标")
        dependent = origin in {"目标属性", "构筑计量", "状态层数", "行动条"} or selector is not None
        if origin == "固定值":
            constant = node.get("固定值", 0)
            read = lambda context, source, selected, amount, values: constant
        elif origin in {"自身属性", "效果来源属性"}:
            attribute = str(node.get("属性") or "")
            read = lambda context, source, selected, amount, values: source.value(attribute)
        elif origin == "目标属性":
            attribute = str(node.get("属性") or "")
            read = lambda context, source, selected, amount, values: selected.value(attribute)
        elif origin == "事件事实":
            fact = str(node.get("事实") or "")
            read = lambda context, source, selected, amount, values: values.get(fact, 0)
        elif origin == "本次数值":
            read = lambda context, source, selected, amount, values: amount
        elif origin == "构筑计量":
            counter = str(node.get("计量") or "")
            instance = node.get("构筑实例")
            read = lambda context, source, selected, amount, values: context.ability_counters.get((selected.id, str(instance or context.current_build_instance or "").strip(), counter), 0)
        elif origin == "状态层数":
            name = str(node.get("状态") or "")
            read = lambda context, source, selected, amount, values: sum(status.stacks for status in selected.statuses.named(name))
        else:
            read = lambda context, source, selected, amount, values: context.action_progress.get(selected.id, 0) * 100
        percent = node.get("百分比", 100)
        has_low, has_high = "最低值" in node, "最高值" in node
        numeric_bounds = type(percent) in (int, float) and (not has_low or type(node['最低值']) in (int, float)) and (not has_high or type(node['最高值']) in (int, float))
        if numeric_bounds:
            percent = float(percent)
            lower = float(node['最低值']) if has_low else None
            upper = float(node['最高值']) if has_high else None

        def evaluate(context: BattleContext, source: Fighter, target: Fighter, _node: Mapping[str, Any], amount: float, values: Mapping[str, Any]) -> Any:
            selected = target
            if dependent:
                destinations = self._select_targets(context, source, target, selector)
                if destinations:
                    selected = destinations[0]
            elif context is None or target is None:
                self._select_targets(context, source, target, None)
            else:
                rules = (target.rules_cache if target.rules_cache_version == context.status_rules_version
                         else self._container_rules(target, context))
                if rules.get("被选为目标"):
                    self._select_targets(context, source, target, None)
            value = read(context, source, selected, amount, values)
            if numeric_bounds and type(value) in (int, float):
                value = float(value) * percent / 100.0
                # 与 max(bound, value) / min(bound, value) 同序，包含 NaN 的边界语义。
                if has_low:
                    value = value if value > lower else lower
                if has_high:
                    value = value if value < upper else upper
                return value
            if type(value) in (int, float) or isinstance(value, (int, float)) and not isinstance(value, bool):
                value = float(value) * float(percent) / 100.0
                if has_low:
                    value = max(float(node["最低值"]), value)
                if has_high:
                    value = min(float(node["最高值"]), value)
            return value

        return evaluate

    def _condition_probability(self, context: BattleContext, source: Fighter, target: Fighter, condition: Mapping[str, Any], *_) -> bool:
        chance = self._resolve_value(context, condition.get("概率", 0), source, target, 0, {}) / 100.0
        return self._judgement(context, "概率", chance)

    def _condition_numeric(self, context: BattleContext | None, source: Fighter | None, target: Fighter | None, condition: Mapping[str, Any], event_amount: float, event_values: Mapping[str, Any], _tags: Iterable[str]) -> bool:
        raw_left = condition.get("左值")
        raw_right = condition.get("右值")
        # 语料中大量条件两侧是冻结的数字常量；这些值不需要经过能力节点解析。
        # 动态读取、事件事实和组合数值仍完整走原解析链。
        left = (
            float(raw_left)
            if type(raw_left) in (int, float)
            else self._resolve_value(context, raw_left, source, target, event_amount, event_values)
        )
        right = (
            float(raw_right)
            if type(raw_right) in (int, float)
            else self._resolve_value(context, raw_right, source, target, event_amount, event_values)
        )
        return self._compare(left, right, str(condition.get("比较") or "等于"))

    def _condition_status(self, context: BattleContext, source: Fighter, target: Fighter, condition: Mapping[str, Any], *_) -> bool:
        destinations = self._select_targets(context, source, target, condition.get("目标"))
        name = str(condition.get("状态") or "")
        count = sum(status.stacks for fighter in destinations for status in fighter.statuses if not name or status.name == name)
        relation = str(condition.get("比较") or "存在")
        if relation == "存在":
            return count > 0
        if relation == "不存在":
            return count == 0
        return self._compare(count, float(condition.get("层数", 1)), relation.removeprefix("层数"))

    def _condition_type(self, context: BattleContext | None, source: Fighter | None, target: Fighter | None, condition: Mapping[str, Any], _amount: float, event_values: Mapping[str, Any], _tags: Iterable[str]) -> bool:
        subject = source if str(condition.get("对象") or "目标") == "来源" else target
        kind = str(condition.get("类型") or "")
        expected = str(condition.get("值") or "")
        if kind == "参战身份":
            return subject.combatant_type == expected or expected in subject.tags
        if kind == "形态":
            return subject.form == expected
        if kind == "性别":
            return subject.gender == expected
        aliases = self._condition_type_aliases
        return str(event_values.get(aliases.get(kind, kind), "")) == expected

    def _condition_combined(self, context: BattleContext | None, source: Fighter | None, target: Fighter | None, condition: Mapping[str, Any], amount: float, values: Mapping[str, Any], tags: Iterable[str]) -> bool:
        results = [self._conditions_allow(context, source, target, (item,), amount, values, tags) for item in condition.get("条件") or ()]
        relation = str(condition.get("关系") or "全部成立")
        if relation == "全部成立":
            return all(results)
        if relation == "任一成立":
            return any(results)
        if relation == "全部不成立":
            return not any(results)
        raise ValueError(f"未知组合条件关系：{relation}")

    def _condition_tags(self, context: BattleContext | None, source: Fighter | None, target: Fighter | None, condition: Mapping[str, Any], _amount: float, event_values: Mapping[str, Any], event_tags: Iterable[str]) -> bool:
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
        if relation == "等于":
            return left == right
        if relation == "不等于":
            return left != right
        if relation == "大于":
            return left > right
        if relation == "大于等于":
            return left >= right
        if relation == "小于":
            return left < right
        if relation == "小于等于":
            return left <= right
        return False

    def _ability_damage(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
        destinations = self._select_targets(context, source, target, effect.get("目标"))
        if not destinations:
            return False
        success = False
        for destination in destinations:
            amount = self._resolve_value(context, effect.get("数值"), source, destination, kwargs.get("event_amount", 0), kwargs.get("event_values") or {}) * multiplier
            amount *= self._element_multiplier(context, source, destination, effect)
            if source.current_skill and str(effect.get("伤害形式") or "直接") == "直接":
                amount *= max(0.0, self._percent(source, "技能威力"))
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

    def _ability_recover_resource(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
        """恢复资源。**资源语义全部来自 `资源.json` 的表**，执行器不认资源名。

        曾经这里有五处 `if 资源 == "血气"` / `"护盾"`：加成属性、事件名、承受方加成
        各查一遍，其中「事件名」那张映射表建完又立刻反解回来
        （`if frame.kind == "获得护盾前": resource = "护盾"`）。加第四个资源必须改代码，
        这正是这个项目其他部分都在避免的事。

        现在每个资源在 `资源.json` 里声明 `恢复前事件` / `恢复后事件` / `加成属性` /
        `受疗加成属性`；两个治愈量属性 `治疗效果`（气血）与 `护盾强度`（护盾）默认
        100，即不缩放卡面数值。精神不设属性，恢复量由卡面数值自己决定。
        """

        requested_resource = str(effect.get("资源") or "血气")
        definition, _resource_field, _cap_attribute, _minimum = self._resource_runtime_entry(requested_resource)
        changed = False
        attempted = False
        for destination in self._select_targets(context, source, target, effect.get("目标")):
            amount = max(0.0, self._resolve_value(context, effect.get("数值"), source, destination, kwargs.get("event_amount", 0), kwargs.get("event_values") or {}) * multiplier)
            amount *= self._element_multiplier(context, source, destination, effect)
            baseline_attribute = str(definition.get("加成属性") or "")
            if baseline_attribute:
                # 基准属性（`治疗效果` / `护盾强度`）：加成口径，基准 100 即 ×1.0。
                amount *= max(0.0, self._percent(source, baseline_attribute))
            builtin_bonus = str(definition.get("卡牌加成属性") or "")
            if builtin_bonus:
                # 卡牌自带加成（`治疗加成` / `护盾加成`）：同样是加成口径、基准 100。
                # 两层各管一件事：基准属性调「这张卡的治愈量整体偏强/偏弱」，自带加成是
                # 卡面词条给的——但两者**读法完全相同**，都走 `_percent`。
                amount *= max(0.0, self._percent(source, builtin_bonus))
            before, maximum = self._resource_values(destination, requested_resource)
            kind = str(definition.get("恢复前事件") or "资源恢复前")
            frame = self._dispatch_event(context, kind=kind, source=source, target=destination, amount=amount, values={"资源": requested_resource, "变化前数值": before, "上限": maximum}, tags=(*effect.get("标签", ()), "恢复", requested_resource))
            if frame.cancelled:
                continue
            # 事件可以被监听者改写，资源身份**不跟着事件名走**：`资源变化` 类监听可能
            # 把事件转成别的名字，但这次恢复的仍然是 `requested_resource`。
            destination = frame.target
            # 恢复已满不是执行失败；后续顺序效果仍必须继续执行。
            attempted = True
            before, maximum = self._resource_values(destination, requested_resource)
            received = max(0.0, frame.amount)
            healed_bonus_attribute = str(definition.get("受疗加成属性") or "")
            if healed_bonus_attribute:
                received *= max(0.0, self._percent(destination, healed_bonus_attribute))
            applied = min(maximum - before, received)
            self._set_resource(destination, requested_resource, before + applied)
            after_event = str(definition.get("恢复后事件") or "资源恢复后")
            values = {"资源": requested_resource, "变化前数值": before, "变化后数值": before + applied, "实际数值": applied, "溢出数值": max(0.0, received - applied)}
            event_tags = (*frame.tags, "恢复", requested_resource)
            self._dispatch_event(context, kind=after_event, source=source, target=destination, amount=applied, values=values, tags=event_tags)
            self._dispatch_event(context, kind="资源变化后", source=source, target=destination, amount=applied, values=values, tags=(*frame.tags, "增加", requested_resource))
            changed = changed or applied > 0
            if applied > 0:
                self._mark_team_synergy(context, source, effect)
        return changed or attempted

    def _resource_definition(self, resource: str) -> Mapping[str, Any]:
        """`资源.json` 里这个资源的定义。未登记的资源直接报错，不静默走默认分支。"""

        definition = self._resource_definitions.get(resource)
        if definition is None:
            raise ValueError(f"战斗核心未登记资源：{resource}")
        return definition

    def _percent(self, fighter: Fighter, attribute: str, default: float | None = None) -> float:
        """读一个百分比属性的比值；基准与口径见 `models.attribute_ratio`。

        与旧实现的两点不同：基准从**属性自己的 `默认值`** 来（不再由调用点写 `1 + …`
        去补），以及 `治疗效果` / `护盾强度` 的专用读法 `_attribute_ratio` 被并入这里——
        它们本来就是「加成口径、基准 100」，不该有两套读法。
        """

        baseline = self._attribute_defaults.get(attribute, 0.0) if default is None else float(default) * 100.0
        return fighter.value(attribute, baseline) / 100.0

    def _element_multiplier(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any]) -> float:
        composition = effect.get("属性构成")
        if not composition:
            return 1.0
        # 属性构成会随继承来源被复制到临时效果节点。按效果身份缓存会保留每次
        # 临时节点及其整棵定义；按标量构成复用只需保留实际出现过的配比。
        composition_key = tuple(composition.items()) if type(composition) is dict else None
        standard = composition_key is not None and all(
            type(key) is str and type(value) in (int, float)
            for key, value in composition_key
        )
        cached = context.element_composition_cache.get(composition_key) if standard else None
        if cached is None:
            values = {str(key): float(value) for key, value in dict(composition).items()}
            cached = (values, tuple(values.items()))
            if standard:
                context.element_composition_cache[composition_key] = cached
        values, composition_signature = cached
        if not values or "无相" in values and len(values) == 1:
            return 1.0
        source_root = source.five_elements
        target_root = target.five_elements
        rules = self.catalog.five_elements
        signature = (composition_signature, tuple(source_root.items()), tuple(target_root.items()))
        result = context.element_multiplier_cache.get(signature)
        multipliers = rules.get("倍率", {})
        if result is None:
            generating = self._element_generating
            overcoming = self._element_overcoming
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
            context.element_multiplier_cache[signature] = result
        for element in values:
            if source.team_synergy.pop(element, 0):
                result *= float(multipliers.get("团队相生", 1.08))
                break
        return result

    def _mark_team_synergy(self, context: BattleContext, source: Fighter, effect: Mapping[str, Any]) -> None:
        composition = effect.get("属性构成") or {}
        generating = self._element_generating
        elements = [generating[element] for element in composition if element in generating]
        if not elements:
            return
        element = elements[0]
        for ally in context.allies_of(source, alive=None):
            if ally is source or ally.team_synergy:
                continue
            ally.team_synergy[element] = 1

    def _ability_consume_resource(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
        resource = str(effect.get("资源") or "精神")
        changed = False
        for destination in self._select_targets(context, source, target, effect.get("目标")):
            amount = max(0.0, self._resolve_value(context, effect.get("数值"), source, destination, kwargs.get("event_amount", 0), kwargs.get("event_values") or {}) * multiplier)
            before, _ = self._resource_values(destination, resource)
            frame = self._dispatch_event(context, kind="资源消耗前", source=source, target=destination, amount=amount, values={"资源": resource, "变化前数值": before}, tags=("消耗", resource))
            destination = frame.target
            # 锁定技：`资源被消耗` 拦截点——问**被扣资源的那个单位**。
            if self._rules_deny(
                context,
                destination,
                "资源被消耗",
                owner=source,
                tags=(
                    "方式:消耗",
                    f"资源:{resource}",
                    f"来源关系:{self._source_relation(context, source, destination)}",
                ),
            ):
                return False
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

    def _ability_pay_cost(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
        kind = str(effect.get("代价类型") or "资源")
        if kind == "资源":
            return self._ability_consume_resource(context, source, target, effect, multiplier, **kwargs)
        if kind == "状态层数":
            # 以状态层数为代价：方向写死在数据里（减少 + 不足即失败），不再靠
            # `consume=` 位置参数告诉执行器「这次是消耗」。
            value = {**effect, "方式": "减少", "不足时是否失败": True}
            return self._ability_modify_status_stacks(context, source, target, value, multiplier)
        if kind == "行动条":
            value = {**effect, "方式": "减少"}
            return self._ability_modify_action_progress(context, source, target, value, multiplier, cost=True)
        if kind == "技能冷却":
            value = {**effect, "方式": "增加"}
            return self._ability_modify_cooldown(context, source, target, value, multiplier)
        if kind == "战斗对象":
            return self._ability_remove_object(context, source, target, effect, multiplier)
        raise ValueError(f"未知代价类型：{kind}")

    def _ability_set_resource(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
        resource = str(effect.get("资源") or "血气")
        changed = False
        for destination in self._select_targets(context, source, target, effect.get("目标")):
            before, maximum = self._resource_values(destination, resource)
            value = self._resolve_value(context, effect.get("数值"), source, destination, kwargs.get("event_amount", 0), kwargs.get("event_values") or {}) * multiplier
            after = self._clamp(value, 0, maximum)
            self._set_resource(destination, resource, after)
            changed = changed or before != after
        return changed

    def _ability_transfer_resource(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
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

    def _ability_add_status(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
        changed = False
        for destination in self._select_targets(context, source, target, effect.get("目标")):
            original = effect.get("状态")
            cached = context.definition_copy_cache.get(id(original))
            if cached is None or cached[0] is not original:
                cached = (original, compile_definition_copy(dict(original or {})))
                context.definition_copy_cache[id(original)] = cached
            definition = cached[1]()
            frame = self._dispatch_event(context, kind="添加状态前", source=source, target=destination, values={"状态": definition.get("名称", ""), "状态定义": definition}, tags=tuple(definition.get("标签") or ()))
            destination = frame.target
            definition["标签"] = sorted(frame.tags)
            failure = ""
            is_control = bool(definition.get("是否控制", False)) or "控制" in frame.tags
            # 锁定技：`状态被添加` 拦截点——问**被打上的那个单位**。请求摊成四类标签
            # （状态名 / 类别 / 是不是控制 / 来源关系），所以「不受控制」「不吃负面状态」
            # 「只不受某一条」都能用现成的条件原子写，不必给引擎加词汇。
            # **拒绝时的说法由登记表给**（规则的 `原因`），所以写法迁移不改战报措辞。
            version = int(getattr(context, "status_rules_version", 0))
            target_rules = (
                destination.rules_cache.get("状态被添加")
                if destination.rules_cache_version == version
                else self._container_rules(destination, context).get("状态被添加")
            )
            refused = None
            if target_rules:
                refused = self._rules_denied_rule(
                    context,
                    destination,
                    "状态被添加",
                    owner=source,
                    tags=(
                        f"状态:{str(definition.get('名称') or '')}",
                        f"类别:{str(definition.get('类别') or '中性')}",
                        f"控制:{'真' if is_control else '假'}",
                        f"来源关系:{self._source_relation(context, source, destination)}",
                    ),
                )
            if frame.cancelled:
                failure = "被取消"
            elif refused is not None:
                failure = str(refused.get("原因") or "状态免疫")
            if not failure and is_control:
                control_limit = int(destination.battle_profile.get("同时承受控制上限", 0))
                if control_limit:
                    active_controls = sum(
                        1
                        for status in destination.statuses
                        if "控制" in status.tags or bool(status.action_limits)
                    )
                    if active_controls >= control_limit:
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
            template = context.status_definition_cache.get(id(original))
            status = None
            if template is not None and template[0] is original and template[1] == definition and same_definition(template[1], definition):
                fields = template[2]
            else:
                status = self._status_with_rules(definition, f"{context.current_ability}.状态")
                fields = status.__dict__ if type(status) is StatusState else {
                    key: getattr(status, key) for key in ('name', 'build_instance', 'stacks', 'remaining_turns')
                }
                if type(status) is StatusState:
                    context.status_definition_cache[id(original)] = (
                        original, copy.deepcopy(definition), copy.deepcopy(status.__dict__)
                    )
            allow_cross_build = bool(definition.get("允许跨构筑", False))
            existing = next(
                (
                    item
                    for item in destination.statuses.named(fields['name'])
                    if (
                        allow_cross_build
                        or not fields['build_instance']
                        or not item.build_instance
                        or fields['build_instance'] == item.build_instance
                    )
                    and (
                        definition.get("叠加范围", "同名共享") == "同名共享"
                        or item.source == source.id
                    )
                ),
                None,
            )
            mode = str(definition.get("重复方式") or "刷新持续")
            previous_status = None if existing is None else (existing.stacks, existing.remaining_turns)
            if existing is None:
                if status is None:
                    status = StatusState.__new__(StatusState)
                    fields = fields.copy()
                    fields['modifiers'] = ModifierMap(fields['modifiers'])
                    fields['rules'] = ModifierMap(copy_value(dict(fields['rules'])))
                    fields['values'] = copy_value(fields['values'])
                    fields['listeners'] = tuple(copy_value(item) for item in fields['listeners'])
                    status.__dict__.update(fields)
                destination.statuses.append(status)
                self._mark_listeners_dirty_for_status(context, status)
            elif mode == "不叠加":
                continue
            elif mode == "增加层数":
                existing.stacks = min(existing.max_stacks, existing.stacks + fields['stacks'])
            elif mode == "增加层数并刷新":
                existing.stacks = min(existing.max_stacks, existing.stacks + fields['stacks'])
                existing.remaining_turns = max(existing.remaining_turns, fields['remaining_turns'])
            elif mode == "延长持续":
                existing.remaining_turns += fields['remaining_turns']
            else:
                existing.remaining_turns = max(existing.remaining_turns, fields['remaining_turns'])
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
                capture=(context.event_capture_filter is None or previous_status != (applied_status.stacks, applied_status.remaining_turns)),
            )
            self._resolve_status_reactions(context, source, destination, fields['name'], multiplier)
            changed = True
        return changed

    def _resolve_status_reactions(self, context: BattleContext, source: Fighter, target: Fighter, added_name: str, multiplier: float) -> None:
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
                        # 锁定技：状态被移除（原因「消耗」）——拒绝时状态反应吃不掉它。
                        if self._status_removal_denied(context, target, status, "消耗", source):
                            continue
                        target.statuses.remove(status)
                        self._mark_listeners_dirty_for_status(context, status)
                generated = reaction.get("生成状态")
                if isinstance(generated, Mapping):
                    value = copy.deepcopy(dict(generated))
                    value["来源"] = source.id
                    value["来源名称"] = source.name
                    value["来源能力"] = context.current_ability
                    value["构筑实例"] = self._build_instance(context, value)
                    generated_status = self._status_with_rules(
                        value, f"{context.current_ability}.生成状态"
                    )
                    target.statuses.append(generated_status)
                    self._mark_listeners_dirty_for_status(context, generated_status)
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

    def _matching_statuses(self, context: BattleContext, fighter: Fighter, selector: Mapping[str, Any]) -> list[StatusState]:
        name = str(selector.get("名称") or "")
        category = str(selector.get("分类") or "")
        tags = {str(value) for value in selector.get("标签") or ()}
        allow_cross_build = bool(selector.get("允许跨构筑", False))
        current_instance = self._build_instance(context, selector)
        # 名称索引已就绪时只检查同名状态；索引失效时沿用扫描，
        # 避免仅为一次状态选择重建属性、规则索引及订阅关系。
        candidates = (
            fighter.statuses.name_index.get(name, ())
            if name and fighter.statuses.modifier_index is not None
            else fighter.statuses
        )
        values = [
            status
            for status in candidates
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

    def _select_statuses(self, context: BattleContext, source: Fighter, target: Fighter, value: object) -> list[tuple[Fighter, StatusState]]:
        if not isinstance(value, Mapping):
            return []
        node = self.catalog.parse_node(value)
        if node.executor != "选择状态":
            raise ValueError("状态字段必须使用选择状态")
        result = []
        for fighter in self._select_targets(context, source, target, value.get("目标")):
            result.extend((fighter, status) for status in self._matching_statuses(context, fighter, value))
        return result

    def _status_removal_denied(
        self, context: BattleContext, owner: Fighter, status: str, reason: str, source: Fighter
    ) -> bool:
        """锁定技：`状态被移除` 拦截点——问**状态挂着的那个单位**。

        `原因` 分四类：`清除`（有人主动清）、`消耗`（状态反应吃掉）、`到期`（自然走完）、
        `来源退场`（挂它的那位没了）。于是「治不好」「不腐」「诅咒摘不掉」都写得出来。
        """

        return self._rules_deny(
            context,
            owner,
            "状态被移除",
            owner=source,
            tags=(
                f"状态:{status.name}",
                f"类别:{status.category}",
                f"原因:{reason}",
                f"来源关系:{self._source_relation(context, source, owner)}",
            ),
        )

    def _ability_remove_status(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
        del multiplier
        pairs = self._select_statuses(context, source, target, effect.get("状态"))
        removed = False
        for owner, status in pairs:
            frame = self._dispatch_event(context, kind="移除状态前", source=source, target=owner, values={"状态": status.name, "状态层数": status.stacks}, tags=status.tags)
            if frame.cancelled:
                continue
            # 锁定技：状态被移除——拒绝时这一次清除不发生（状态还在）。
            if self._status_removal_denied(context, owner, status, "清除", source):
                continue
            if status in owner.statuses:
                owner.statuses.remove(status)
                self._mark_listeners_dirty_for_status(context, status)
                self._dispatch_event(context, kind="移除状态后", source=source, target=owner, values={"状态": status.name, "状态层数": status.stacks}, tags=status.tags)
                removed = True
        return removed

    def _ability_modify_status_stacks(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
        """改状态层数。方向由 `方式` 决定（`增加` / `减少`），没有第二个开关。

        曾经这里还认一个 `consume=True` 位置参数和 `数值` 字段名兜底——那是
        `增加状态层数` / `消耗状态层数` 两个能力名共用一个执行器时留下的：方向既能
        由能力名决定、又能由 `方式` 决定，还能由 `consume` 决定。现在只有 `方式`。
        """

        pairs = self._select_statuses(context, source, target, effect.get("状态"))
        amount = max(0, int(float(effect.get("层数", 1)) * multiplier))
        if not pairs:
            return False
        consume = str(effect.get("方式") or "增加") == "减少"
        for owner, status in pairs:
            before = status.stacks
            if consume:
                if before < amount and effect.get("不足时是否失败", True):
                    return False
                status.stacks = max(0, before - amount)
            else:
                status.stacks = min(status.max_stacks, before + amount)
            if status.stacks <= 0 and status in owner.statuses:
                # 锁定技：状态被移除（原因「消耗」）——拒绝时状态留着，层数按 0 记。
                if not self._status_removal_denied(context, owner, status, "消耗", source):
                    owner.statuses.remove(status)
                    self._mark_listeners_dirty_for_status(context, status)
            self._dispatch_event(context, kind="状态层数变化后", source=source, target=owner, values={"状态": status.name, "变化前数值": before, "变化后数值": status.stacks})
        return True

    def _ability_modify_status_duration(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
        pairs = self._select_statuses(context, source, target, effect.get("状态"))
        amount = max(0, int(float(effect.get("持续数值", 1)) * multiplier))
        mode = str(effect.get("方式") or "增加")
        for _, status in pairs:
            status.remaining_turns = max(0, status.remaining_turns + (amount if mode == "增加" else -amount))
        return bool(pairs)

    def _ability_copy_status(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
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
                self._mark_listeners_dirty_for_status(context, copied)
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

    def _ability_transfer_status(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
        pairs = self._select_statuses(context, source, target, effect.get("状态"))
        receivers = self._select_targets(context, source, target, effect.get("接收目标"))
        if not pairs or not receivers:
            return False
        for owner, status in pairs:
            owner.statuses.remove(status)
            receivers[0].statuses.append(status)
            self._mark_listeners_dirty_for_status(context, status)
        return True

    def _ability_modify_action_progress(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, cost: bool=False, **_) -> bool:
        amount = max(0.0, float(effect.get("数值", 0)) * multiplier) / 100.0
        mode = str(effect.get("方式") or "增加")
        changed = False
        for destination in self._select_targets(context, source, target, effect.get("目标")):
            # 规则层：`行动条被改写` 拦截点。挡的是这一次改写，不是「这个人不许被推」。
            if self._rules_deny(
                context,
                destination,
                "行动条被改写",
                owner=source,
                tags=(
                    f"方式:{mode}",
                    f"来源关系:{self._source_relation(context, source, destination)}",
                ),
                values={"数值": amount * 100},
                amount=amount * 100,
            ):
                continue
            before = context.action_progress.get(destination.id, 0.0)
            if cost and before < amount:
                return False
            after = amount if mode == "设置" else before + amount if mode == "增加" else before - amount
            after = self._clamp(after, 0.0, 0.999999)
            context.action_progress[destination.id] = after
            self._dispatch_event(context, kind="行动条变化后", source=source, target=destination, amount=(after - before) * 100, values={"变化前数值": before * 100, "变化后数值": after * 100})
            changed = changed or before != after
        return changed

    def _ability_modify_cooldown(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
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

    def _ability_modify_counter(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
        static = context.ability_static_cache.get(id(effect))
        if static is None or static[0] is not effect:
            static = (
                effect,
                str(effect.get("计量") or ""),
                str(effect.get("方式") or "增加"),
                float(effect.get("初始值", 0)),
                bool(effect.get("不足时是否失败", True)),
                float(effect.get("最低值", 0)),
                float(effect.get("最高值", 100)),
            )
            context.ability_static_cache[id(effect)] = static
        _, name, mode, initial, insufficient_fails, minimum, maximum = static
        instance = self._build_instance(context, effect)
        amount = self._resolve_value(context, effect.get("数值", 0), source, target, kwargs.get("event_amount", 0), kwargs.get("event_values") or {}) * multiplier
        changed = False
        for fighter in self._select_targets(context, source, target, effect.get("目标")):
            # 锁定技：`计量被修改` 拦截点——问**计量记在谁身上**。
            version = int(getattr(context, "status_rules_version", 0))
            rules = (
                fighter.rules_cache.get("计量被修改")
                if fighter.rules_cache_version == version
                else self._container_rules(fighter, context).get("计量被修改")
            )
            if rules and self._rules_deny(
                context,
                fighter,
                "计量被修改",
                owner=source,
                tags=(
                    f"计量:{name}",
                    f"方式:{mode}",
                    f"来源关系:{self._source_relation(context, source, fighter)}",
                ),
            ):
                continue
            key = (fighter.id, instance, name)
            before = context.ability_counters.get(key, initial)
            if mode == "减少" and before < amount and insufficient_fails:
                return False
            after = amount if mode == "设置" else 0 if mode == "清空" else before + amount if mode == "增加" else before - amount
            after = self._clamp(after, minimum, maximum)
            context.ability_counters[key] = after
            changed = changed or before != after
        return changed

    @staticmethod
    def _build_instance(context: BattleContext, node: Mapping[str, Any] | None = None) -> str:
        """解析当前能力所属构筑实例；公共能力保持空作用域。"""

        value = (node or {}).get("构筑实例") if isinstance(node, Mapping) else None
        return str(value or context.current_build_instance or "").strip()

    def _ability_additional_attack(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
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

    def _ability_share_damage(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
        frame = self._current_event(context, "造成伤害前")
        destinations = self._select_targets(context, source, target, effect.get("目标"))
        if not destinations:
            return False
        amount = max(0.0, frame.amount * float(effect.get("比例", 0)) / 100.0 * multiplier)
        frame.facts["当前数值"] = max(0.0, frame.amount - amount)
        self._apply_damage(context, frame.source, destinations[0], amount, label=str(effect.get("名称") or "分摊伤害"), damage_form="分摊", defense_rule="真实", can_critical=False, can_block=False, tags=("分摊",))
        return True

    def _ability_transfer_damage(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
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

    def _ability_fatal_guard(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
        frame = self._current_event(context, "受到致命伤害")
        amount = max(1.0, float(effect.get("保留血气", 1)) * multiplier)
        frame.facts["保留血气"] = max(float(frame.facts.get("保留血气", 0)), amount)
        frame.cancelled = True
        return True

    def _ability_revive(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
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

    def _event_rewrite_denied(self, context: BattleContext, frame: EventFrame, kind: str) -> bool:
        """规则层：`事件被改写` 拦截点——问**这件事的承受者**愿不愿意被改写。

        语义是「关于我的事件不能被取消/转化/改数值」，所以问的是 `frame.target`，
        请求编码成标签 `改写:取消`、`改写:转化`、`改写:数值`、`改写:目标`、`改写:标签`。
        """

        if frame is None or frame.target is None:
            return False
        return self._rules_deny(
            context,
            frame.target,
            "事件被改写",
            owner=frame.target,
            tags=(f"改写:{kind}",),
            values=dict(frame.facts or {}),
            amount=float(frame.amount or 0.0),
        )

    def _ability_modify_event_value(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
        frame = self._current_event(context)
        if not self._event_mutation_allowed(frame, "当前数值"):
            return False
        if self._event_rewrite_denied(context, frame, "数值"):
            return False
        amount = self._resolve_value(context, effect.get("数值"), source, target, kwargs.get("event_amount", frame.amount), frame.facts) * multiplier
        mode = str(effect.get("方式") or "设置")
        frame.facts["当前数值"] = max(0.0, amount if mode == "设置" else frame.amount + amount if mode == "增加" else frame.amount - amount if mode == "减少" else frame.amount * amount / 100.0)
        return True

    def _ability_modify_event_target(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
        del multiplier
        frame = self._current_event(context)
        if not self._event_mutation_allowed(frame, "目标"):
            return False
        if self._event_rewrite_denied(context, frame, "目标"):
            return False
        values = self._select_targets(context, source, target, effect.get("目标"))
        if not values:
            return False
        frame.target = values[0]
        frame.facts["承受者"] = values[0].id
        return True

    def _ability_modify_event_tags(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
        del source, target, multiplier
        frame = self._current_event(context)
        if not self._event_mutation_allowed(frame, "标签"):
            return False
        if self._event_rewrite_denied(context, frame, "标签"):
            return False
        values = {str(value) for value in effect.get("标签") or ()}
        mode = str(effect.get("方式") or "添加")
        frame.tags = values if mode == "设置" else frame.tags - values if mode == "移除" else frame.tags | values
        frame.facts["标签"] = sorted(frame.tags)
        return True

    def _ability_cancel_event(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
        del source, target, effect, multiplier
        frame = self._current_event(context)
        if not self._event_mutation_allowed(frame, "取消"):
            return False
        if self._event_rewrite_denied(context, frame, "取消"):
            return False
        frame.cancelled = True
        frame.facts["已取消"] = True
        return True

    def _ability_trigger_skill(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
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

    def _ability_record_fact(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
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

    def _ability_modify_relation(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
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

    def _ability_modify_skill(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
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

    def _ability_copy_skill(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
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

    def _ability_modify_intent(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
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

    def _ability_transform_event(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
        del multiplier
        frame = self._current_event(context)
        destination = str(effect.get("事件") or "")
        self.catalog.require_event(destination)
        if frame is None:
            return False
        # 转化只在三种「资源到手之前」的事件之间有共同结算语义。**不合法就拒绝这次转化
        # 并留痕，不抛错**：同一个能力在别的上下文里可能合法（效果会被保存后回放，
        # 回放时的当前事件与声明时不同），一条录下来的效果回放到别的时点，不该把整场
        # 战斗炸掉。与「事件链到顶不再往下触发」同一口径。
        if not self._event_mutation_allowed(frame, "类型"):
            return False
        if self._event_rewrite_denied(context, frame, "转化"):
            return False
        transformable = self._transformable_events()
        if frame.kind not in transformable or destination not in transformable:
            self._refuse_event_mutation(frame, f"{frame.kind} 不能转化为 {destination}")
            return False
        frame.transformed_kind = destination
        self._dispatch_event(context, kind="事件转化后", source=source, target=target, values={"原事件": frame.kind, "新事件": destination})
        return True

    @staticmethod
    def _transformable_events() -> frozenset[str]:
        """可以互相转化的三种事件：都在「资源还没到手」之前，语义可换。"""

        return frozenset({"恢复前", "获得护盾前", "资源恢复前"})

    def _ability_modify_judgement(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
        del source, target, multiplier
        kind = str(effect.get("判定") or "任意")
        context.judgement_overrides.setdefault(kind, []).append({"方式": str(effect.get("方式") or "必定成功"), "次数": max(1, int(effect.get("次数", 1)))})
        return True

    def _ability_modify_battle_rule(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
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
                and (duplicate_mode != "同源唯一" or
                     (rule.get("来源") == source.id and rule.get("构筑实例", "") == context.current_build_instance))
            ]
            if existing and duplicate_mode in {"拒绝", "已存在则拒绝", "同源唯一"}:
                return False
            definition = copy.deepcopy(dict(effect.get("规则") or {}))
            unknown = set(definition) - {"监听"}
            if unknown:
                raise ValueError("战场规则存在无执行语义字段：" + "、".join(sorted(unknown)))
            context.battle_rule_serial += 1
            context.battle_rules.append({
                **definition,
                "运行编号": context.battle_rule_serial,
                "构筑实例": context.current_build_instance,
                "名称": name,
                "来源": source.id,
                "来源退场时移除": bool(effect.get("来源退场时移除", False)),
            })
            context.mark_listener_index_dirty()
            changed = True
        self._dispatch_event(context, kind="战场规则变化后", source=source, target=source, values={"规则": name, "方式": mode})
        return changed

    def _ability_save_result(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
        name = str(effect.get("名称") or "")
        source_name = str(effect.get("来源") or "上个效果")
        value = context.last_result if source_name == "上个效果" else self._resolve_any(context, effect.get("值"), source, target, kwargs.get("event_amount", 0), kwargs.get("event_values") or {})
        context.saved_results[name] = copy.deepcopy(value)
        return True

    def _ability_switch_form(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
        changed = False
        for fighter in self._select_targets(context, source, target, effect.get("目标")):
            name = str(effect.get("形态") or "")
            definition = dict(effect.get("定义") or fighter.forms.get(name) or {})
            if not name or fighter.form == name:
                continue
            # 锁定技：`形态被切换` 拦截点——问**要被切形态的那个单位**。
            if self._rules_deny(
                context,
                fighter,
                "形态被切换",
                owner=source,
                tags=(
                    f"形态:{name}",
                    f"来源关系:{self._source_relation(context, source, fighter)}",
                ),
            ):
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
                fighter.base_form_skills = copy_skills(fighter.skills)
            if definition.get("替换技能"):
                fighter.skills = [self._skill_from_definition(fighter, index, value) for index, value in enumerate(definition["替换技能"])]
            else:
                fighter.skills = copy_skills(fighter.base_form_skills)
            if not definition.get("保留冷却", True):
                fighter.cooldowns.clear()
            fighter.form = name
            self._dispatch_event(context, kind="形态切换后", source=source, target=fighter, values={"原形态": before, "形态": name})
            changed = True
        return changed

    def _ability_create_object(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
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

    def _ability_remove_object(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
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

    def _retire_battle_object(self, context: BattleContext, source: Fighter, fighter: Fighter, kind: str, *, object_id: str="") -> bool:
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

    def _remove_source_lifetimes(self, context: BattleContext, source: Fighter) -> None:
        for fighter in context.fighters:
            expired = [status for status in fighter.statuses if status.expire_with_source and status.source == source.id]
            for status in expired:
                # 锁定技：状态被移除（原因「来源退场」）——拒绝时这条状态不跟着走。
                if self._status_removal_denied(context, fighter, status, "来源退场", source):
                    continue
                fighter.statuses.remove(status)
                self._mark_listeners_dirty_for_status(context, status)
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

    def _ability_modify_ownership(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
        del multiplier
        values = self._select_targets(context, source, target, effect.get("目标"))
        if not values:
            return False
        destination = values[0]
        field = str(effect.get("字段") or "阵营")
        # 锁定技：`归属被修改` 拦截点——问**被改归属的那个单位**。
        if self._rules_deny(
            context,
            destination,
            "归属被修改",
            owner=source,
            tags=(
                f"字段:{field}",
                f"来源关系:{self._source_relation(context, source, destination)}",
            ),
        ):
            return False
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

    def _ability_replay_effect(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **kwargs) -> bool:
        scope = str(effect.get("范围") or "上个效果")
        history = [item for item in context.effect_history if item.get("成功")]
        if scope == "自身上个效果":
            history = [item for item in history if item.get("来源") == source.id]
        if not history:
            return False
        item = copy.deepcopy(history[-1])
        destinations = self._select_targets(context, source, target, effect.get("目标")) or [target]
        return self._execute_mechanism(context, source, destinations[0], item["节点"], float(item.get("倍率", 1)) * float(effect.get("倍率", 1)) * multiplier, **kwargs)

    def _ability_modify_tactic(self, context: BattleContext, source: Fighter, target: Fighter, effect: Mapping[str, Any], multiplier: float, **_) -> bool:
        del multiplier
        changed = False
        for fighter in self._select_targets(context, source, target, effect.get("目标")):
            mode = str(effect.get("方式") or "替换")
            rules = copy.deepcopy(list(effect.get("战术") or ()))
            fighter.tactic = rules if mode == "替换" else [*fighter.tactic, *rules] if mode == "追加" else []
            changed = True
        return changed

    def _select_skills(self, context: BattleContext, fighter: Fighter, value: object) -> list[str]:
        if not isinstance(value, Mapping):
            return []
        node = self.catalog.parse_node(value)
        if node.executor != "选择技能":
            raise ValueError("技能字段必须使用选择技能")
        return self._skills_select(context, fighter, fighter, value, 0, {}, ())

    def _skills_select(self, context: BattleContext, source: Fighter, target: Fighter, selector: Mapping[str, Any], *_) -> list[str]:
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

    def _resolve_value(self, context: BattleContext | None, value: Any, source: Fighter | None, target: Fighter | None, event_amount: float=0.0, event_values: Mapping[str, Any] | None=None) -> float:
        if type(value) in (int, float):
            return float(value)
        result = self._resolve_any(context, value, source, target, event_amount, event_values or {})
        if isinstance(result, bool) or not isinstance(result, (int, float)):
            raise TypeError(f"战斗数值必须是数字：{result!r}")
        return float(result)

    def _resolve_any(self, context: BattleContext | None, value: Any, source: Fighter | None, target: Fighter | None, event_amount: float=0.0, event_values: Mapping[str, Any] | None=None) -> Any:
        if isinstance(value, Mapping):
            if "能力" not in value:
                return copy_value(dict(value))
            # 与 `_execute_mechanism` / 目标解析两处同一手法：先按对象身份查一次缓存，省掉
            # `parse_node` 的**调用开销**（这一处实测 7,583 次调用里 6,591 次命中）。取值算子里
            # 只有带「能力」的 Mapping 才走解析，`value` 来自装配期冻结的内容、一场里不换。
            # **`context` 可能为 `None`**（规则层那类「没有战斗现场也要算一遍」的用法），
            # 所以先判空、没有现场就退回 `parse_node`——语义一字不差；交给处理器的仍是 `dict(value)` 副本。
            node = context.ability_node_cache.get(id(value)) if context is not None else None
            if node is None or node.values is not value:
                node = self.catalog.parse_node(value)
                if context is not None:
                    context.ability_node_cache[id(value)] = node
            handler = self._value_handlers.get(node.executor)
            if handler is None:
                raise ValueError(f"战斗核心未实现数值执行器：{node.executor or '<空>'}")
            return handler(context, source, target, value, event_amount, event_values or {})
        return value if value is not None else 0

    def _value_read(self, context: BattleContext | None, source: Fighter | None, target: Fighter | None, node: Mapping[str, Any], event_amount: float, event_values: Mapping[str, Any]) -> Any:
        origin = str(node.get("来源") or "固定值")
        target_value_origins = {
            "目标属性",
            "战斗记录",
            "构筑计量",
            "状态层数",
            "行动条",
            "技能冷却",
        }
        selected = target
        target_dependent = (
            origin in target_value_origins
            or origin.startswith(("目标当前", "目标已损失"))
        )
        if target_dependent or node.get("目标") is not None:
            destinations = self._select_targets(context, source, target, node.get("目标")) or [target]
            selected = destinations[0]
        elif context is None or target is None:
            self._select_targets(context, source, target, None)
        else:
            version = context.status_rules_version
            if target.rules_cache_version == version:
                has_selection_rule = bool(target.rules_cache.get("被选为目标"))
            else:
                has_selection_rule = bool(
                    self._container_rules(target, context).get("被选为目标")
                )
            if has_selection_rule:
                self._select_targets(context, source, target, None)
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
            status_name = str(node.get("状态") or "")
            value = sum(status.stacks for status in selected.statuses.named(status_name))
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

    def _value_calculate(self, context: BattleContext, source: Fighter, target: Fighter, node: Mapping[str, Any], amount: float, values: Mapping[str, Any]) -> float:
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

    def _value_random(self, context: BattleContext, source: Fighter, target: Fighter, node: Mapping[str, Any], *_) -> float:
        del source, target
        low, high = float(node.get("最低值", 0)), float(node.get("最高值", 0))
        value = context.rng.uniform(low, high)
        return round(value) if node.get("取整", False) else value

    def _value_aggregate(self, context: BattleContext, source: Fighter, target: Fighter, node: Mapping[str, Any], amount: float, values: Mapping[str, Any]) -> float:
        targets = self._select_targets(context, source, target, node.get("目标"))
        mode = str(node.get("方式") or "数量")
        if mode == "数量":
            return float(len(targets))
        data = [self._resolve_value(context, node.get("数值"), source, fighter, amount, values) for fighter in targets]
        if not data:
            return 0.0
        return {"总和": sum(data), "最小": min(data), "最大": max(data), "平均": sum(data) / len(data), "不同值数量": float(len(set(data)))}.get(mode, 0.0)

    def _status_with_rules(self, definition: Mapping[str, Any], path: str) -> StatusState:
        """把状态定义里的 `规则[]` 一并解析，再建 `StatusState`。

        状态是**锁定技在内容里的第三种写法**：作者把单位级规则写在状态定义里，状态挂上就生效、
        状态一没就失效（规则本身仍不进效果管线）。解析放在这里而不是模型里，是因为
        只有运行期拿得到规则层登记表与报错路径。
        """

        from .models import StatusState
        from .rules import RULE_FIELD, parse_rule_entries

        entries = definition.get(RULE_FIELD)
        rules = (
            parse_rule_entries(
                entries,
                self.catalog.rule_layer,
                carrier="单位",
                path=path,
            )
            if entries
            else {}
        )
        status = StatusState.from_dict(definition)
        if rules:
            status.rules.update(rules)
        return status

    def _source_relation(self, context: BattleContext | None, source: Fighter | None, candidate: Fighter) -> str:
        """规则里的 `来源关系` 看的是「谁在动手」，所以只分自身 / 己方 / 敌方。"""

        if source is None or candidate is None:
            return "任意"
        if source is candidate:
            return "自身"
        return "己方" if source.side == candidate.side else "敌方"

    def _rules_deny(
        self,
        context: BattleContext | None,
        container: Fighter | Skill,
        point: str,
        *,
        owner: Fighter | None=None,
        tags: tuple = (),
        values: Mapping[str, Any] | None=None,
        amount: float = 0.0,
    ) -> bool:
        """问一个载体的规则：这次改写/选定被拒绝了吗（只看结论）。"""

        return (
            self._rules_denied_rule(
                context,
                container,
                point,
                owner=owner,
                tags=tags,
                values=values,
                amount=amount,
            )
            is not None
        )

    def _container_rules(self, container: Fighter | Skill, context: BattleContext | None) -> dict[str, tuple]:
        """按拦截点分好的规则表，**带版本号记忆化**。

        规则来自两处：载体自己带的（装配期定死）、在场状态带的（跟状态生灭）。以前每次问都
        要把身上每个状态扫一遍再排序——实战里 7.6 万次调用、占了一成多时间。现在按
        `context.status_rules_version` 缓存：状态一进出（或回滚）版本号上加一，缓存作废。

        键是**载体对象自己**（修士或技能行），所以技能行那份也一并享受。
        """

        version = int(getattr(context, "status_rules_version", 0))
        if getattr(container, "rules_cache_version", -1) == version:
            return container.rules_cache
        built: dict[str, list] = {}
        for rule in (getattr(container, "rules", None) or {}).values():
            built.setdefault(str(rule.get("拦截点") or ""), []).append(rule)
        statuses = getattr(container, "statuses", None)
        for status in statuses.with_rules() if statuses else ():
            for rule in (getattr(status, "rules", None) or {}).values():
                built.setdefault(str(rule.get("拦截点") or ""), []).append(rule)
        cache = {
            point: tuple(sorted(rules, key=lambda rule: int(rule.get("优先级") or 0)))
            for point, rules in built.items()
        }
        container.rules_cache = cache
        container.rules_cache_version = version
        return cache

    def _rules_denied_rule(
        self,
        context: BattleContext | None,
        container: Fighter | Skill,
        point: str,
        *,
        owner: Fighter | None=None,
        tags: tuple = (),
        values: Mapping[str, Any] | None=None,
        amount: float = 0.0,
    ) -> dict[str, Any] | None:
        """问一个载体的规则，返回**拍板拒绝的那一条**（没拒绝就返回 `None`）。

        需要结论的调用方用 `_rules_deny`；需要知道「是谁拦的」的调用方用这个——例如
        `状态被添加` 要用登记表里的 `原因` 说明这次拒绝叫什么（`控制免疫` / `状态免疫`），
        这样把内容从旧的写法迁到锁定技，战报里的措辞一个字都不用变。

        `container` 是**规则写在谁身上**（参战者，或一条技能行）；`owner` 是条件求值时的
        「来源」（通常就是持有者）。按优先级升序问；后问的规则只有在先成立的那条允许被它
        改写（`可改写`）时才能改变结论——所以优先级与可改写都真有语义。

        **单位级规则有四处写法**：卡面根能力 `规则文本`、被动技能行、状态定义、参战者
        `固有规则`（见 `data/战斗/说明.md`）。前三处在装配期就并进`参战者.规则`；状态带的那一份
        **跟状态一起生灭**，所以每次问的时候从在场状态里现取。
        """

        rules = self._container_rules(container, context).get(point) or ()
        if not rules:
            return None
        subject = owner if owner is not None else container
        verdict = None
        decision = None
        for rule in rules:
            if verdict is not None and str(rule.get("名称")) not in tuple(verdict.get("可改写") or ()):
                continue
            rule_conditions = rule.get("条件") or ()
            if rule_conditions and not self._conditions_allow(
                context,
                subject,
                subject,
                rule_conditions,
                amount,
                values or {},
                tags,
            ):
                continue
            verdict = rule
            decision = str(rule.get("处置") or "")
        return verdict if decision == "拒绝" else None

    def _select_targets(self, context: BattleContext | None, source: Fighter | None, target: Fighter | None, value: object) -> list[Fighter]:
        """解析一个「目标/来源目标/归属」字段。

        三种写法都接受：

            （省略）                 -> 与原实现一致，即「当前目标」
            "当前目标"               -> 简写，只指定范围
            {能力: 选择目标, 范围: …} -> 完整写法

        省略没有取「自身」，虽然「自身」占全部目标的 84%（16270/18647）：各调用点
        传进来的 `target` 语义不同，把缺省改成「自身」会让 19 张功法改变行为
        （1967 场语料对照实测）。所以省略保持原语义，「自身」必须显式写出。
        """
        if context is None:
            return self._select_targets_uncached(context, source, target, value)
        cached = context.target_selector_cache.get(id(value))
        if cached is None or cached[0] is not value:
            if value is None:
                selector = _SCOPE_SELECTORS[DEFAULT_TARGET_SCOPE]
            elif isinstance(value, str):
                scope = value.strip()
                if scope not in TARGET_SCOPES:
                    raise ValueError('未知目标范围：' + (scope or '<空>') + '；可用：' + '、'.join(TARGET_SCOPES))
                selector = _SCOPE_SELECTORS[scope]
            elif isinstance(value, Mapping):
                selector = value
            else:
                raise TypeError('目标字段必须是范围名或选择目标对象')
            if self.catalog.parse_node(selector).executor != '选择目标':
                raise ValueError('目标字段必须使用选择目标')
            scope = str(selector.get('范围') or '当前目标')
            simple = scope if selector.keys() <= _TARGET_SELECTOR_BARE_KEYS and scope in {'自身', '当前目标'} else None
            cached = (value, selector, simple)
            context.target_selector_cache[id(value)] = cached
        if cached[2] is not None:
            chosen = source if cached[2] == '自身' else target
            return self._single_target(context, source, chosen)
        return self._target_select(context, source, target, cached[1])

    def _select_targets_uncached(self, context: BattleContext | None, source: Fighter | None, target: Fighter | None, value: object) -> list[Fighter]:
        if value is None:
            selector = _SCOPE_SELECTORS[DEFAULT_TARGET_SCOPE]
        elif isinstance(value, str):
            scope = value.strip()
            if scope not in TARGET_SCOPES:
                raise ValueError('未知目标范围：' + (scope or '<空>') + '；可用：' + '、'.join(TARGET_SCOPES))
            selector = _SCOPE_SELECTORS[scope]
        elif isinstance(value, Mapping):
            selector = value
        else:
            raise TypeError('目标字段必须是范围名或选择目标对象')
        if self.catalog.parse_node(selector).executor != '选择目标':
            raise ValueError('目标字段必须使用选择目标')
        return self._target_select(context, source, target, selector)

    def _single_target(self, context: BattleContext | None, source: Fighter | None, chosen: Fighter | None) -> list[Fighter]:
        if chosen is None or not chosen.alive or chosen.combatant_type == '构造物':
            return []
        version = getattr(context, 'status_rules_version', 0)
        rules = chosen.rules_cache if chosen.rules_cache_version == version else self._container_rules(chosen, context)
        if rules.get('被选为目标') and self._rules_deny(context, chosen, '被选为目标', owner=source, tags=(f'来源关系:{self._source_relation(context, source, chosen)}',)):
            return []
        return [chosen]

    def _target_select(self, context: BattleContext | None, source: Fighter | None, target: Fighter | None, selector: Mapping[str, Any], *_) -> list[Fighter]:
        if selector.keys() <= _TARGET_SELECTOR_BARE_KEYS:
            scope = str(selector.get('范围') or '当前目标')
            if scope in {'自身', '当前目标'}:
                return self._single_target(context, source, source if scope == '自身' else target)
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
        # 规则层：`被选为目标` 拦截点。规则是常驻事实，所以这里只判合法性，
        # 不产生事件、也不进战报的事件明细（它不是「发生了什么」，是「本来就不能选他」）。
        eligible = []
        for value in candidates:
            version = context.status_rules_version
            rules = value.rules_cache if value.rules_cache_version == version else self._container_rules(value, context)
            # 与单目标路径相同：没有目标拦截规则时，无须构造关系标签或调用条件解释器。
            # 只跳过空规则集；动态状态、阵营变化仍按规则版本重新读取。
            if not rules.get("被选为目标") or not self._rules_deny(
                context, value, "被选为目标", owner=source,
                tags=(f"来源关系:{self._source_relation(context, source, value)}",),
            ):
                eligible.append(value)
        candidates = eligible
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

    #: 资源 -> `Fighter` 上承载它的属性名。资源身份与字段名的对应关系在这里写一次，
    #: 不再散成 `if 资源 == "血气": return target.health` 这样的三分支（加第四个资源
    #: 就要在每处补一条）。
    _RESOURCE_FIELDS = {
        "血气": "health",
        "精神": "spirit",
        "护盾": "shield",
    }

    def _resource_values(self, target: Fighter, resource: str) -> tuple[float, float]:
        """`(当前值, 上限)`。上限取资源声明的 `上限属性`。"""

        definition, field, cap_attribute, _minimum = self._resource_runtime_entry(resource)
        maximum = target.value(cap_attribute, 0.0) if cap_attribute else 0.0
        return float(getattr(target, field)), max(0.0, float(maximum))

    def _set_resource(self, target: Fighter, resource: str, value: float) -> None:
        _definition, field, _cap_attribute, minimum = self._resource_runtime_entry(resource)
        setattr(target, field, max(float(minimum), float(value)))

    def _resource_runtime_entry(self, resource: str) -> tuple[Mapping[str, Any], str, str, float]:
        entry = self._resource_runtime.get(resource)
        if entry is None:
            self._resource_definition(resource)
            raise AssertionError("unreachable")
        if entry[1] is None:
            raise ValueError(f"战斗核心未登记资源的承载字段：{resource}")
        return entry

    def _resource_field(self, resource: str) -> str:
        field = self._RESOURCE_FIELDS.get(resource)
        if field is None:
            raise ValueError(f"战斗核心未登记资源的承载字段：{resource}")
        return field

    def _current_event(self, context: BattleContext, expected: str | None = None) -> EventFrame:
        if not context.event_stack:
            raise ValueError("当前没有可以修改的战斗事件")
        frame = context.event_stack[-1]
        if expected and frame.kind != expected:
            raise ValueError(f"当前事件不是{expected}")
        return frame

    def _event_mutation_allowed(self, frame: EventFrame, field: str) -> bool:
        """这次改写事件在白名单里吗；不在就**拒绝并留痕**（见 `_refuse_event_mutation`）。

        白名单本身是数据（`定义/事件.json` 的 `可修改`），它拦的是「作者写错了挂钩的事件」；
        运行期还会遇到**声明合法、落到别的时点却越界**的情形（保存下来的效果被回放时，
        当前事件与声明时不同）。后者不该把整场战斗炸掉，所以运行期是拒绝 + 事实留痕，
        作者写错则由静态判据当场报出来。
        """

        contract = self.catalog.require_event(frame.kind)
        if field in set(contract.get("可修改") or ()):
            return True
        self._refuse_event_mutation(frame, f"事件 {frame.kind} 不允许修改{field}")
        return False

    @staticmethod
    def _refuse_event_mutation(frame: EventFrame, reason: str) -> None:
        """把「这次改写被拒」记进事件事实，战报与事后审都看得到。"""

        frame.facts["改写非法"] = reason

    def _judgement(self, context: BattleContext, kind: str, chance: float, roll: float | None=None) -> bool:
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
    def _skill_by_key(fighter: Fighter, key: str) -> Skill | None:
        return next((skill for skill in fighter.skills if skill.key == key), None)

    @staticmethod
    def _skill_available(fighter: Fighter, skill: Skill) -> bool:
        return not skill.disabled and (not skill.use_limit or skill.uses < skill.use_limit) and fighter.cooldowns.get(skill.key, 0) <= 0

    def _skill_order_key(self, skill: Skill) -> tuple:
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
    def _skill_from_definition(owner: Fighter, index: int, definition: Mapping[str, Any], prefix: str="") -> Skill:
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
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return min(float(maximum), max(float(minimum), float(value)))
