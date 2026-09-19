"""把构筑的能力树渲染成玩家读的规则正文。

`说明` 里从「主动」开始的正文由本模块生成，卡头那行风味简介仍由人写。
渲染规则见 `data/战斗/内容/文本规范.md`；本模块是那份规范的唯一实现。

三条硬要求：

* **不猜**。只写引擎已经能表达的东西。节点里没有的语义一律不补。
* **不漏**。任何一个原子能力、任何一个事件都必须有措辞；认不出来就记进
  `unknown` 并在正文里留下 `〈未支持：X〉`，由 `tools/架构审查/检查描述一致.py` 报错。
* **不改数据**。渲染是只读的，拿同一棵树渲染两次必须完全一样。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from .mechanics import DEFAULT_TARGET_SCOPE

#: 事件名 -> 玩家读的时机短语。事件表里的名字是引擎口径，这里是文本口径。
EVENT_PHRASES = {
    "战斗开始": "战斗开始时",
    "战场形成": "战场形成时",
    "行动开始": "行动开始时",
    "行动结束": "行动结束时",
    "行动决策前": "行动前",
    "行动决策后": "行动后",
    "行动跳过后": "行动被跳过后",
    "行动条变化后": "行动条变化后",
    "行动意图变化后": "行动意图变化后",
    "普通攻击前": "普通攻击前",
    "普通攻击后": "普通攻击后",
    "受到伤害后": "受到伤害后",
    "受到致命伤害": "受到致命伤害时",
    "造成伤害前": "造成伤害前",
    "造成伤害后": "造成伤害后",
    "命中判定前": "命中判定前",
    "命中后": "命中后",
    "闪避后": "闪避后",
    "暴击判定前": "暴击判定前",
    "暴击后": "暴击后",
    "格挡判定前": "格挡判定前",
    "格挡后": "格挡后",
    "追加攻击后": "追加攻击后",
    "护盾吸收后": "护盾吸收后",
    "护盾破碎后": "护盾破碎后",
    "获得护盾前": "获得护盾前",
    "获得护盾后": "获得护盾后",
    "恢复前": "恢复前",
    "恢复后": "恢复后",
    "资源恢复前": "恢复资源前",
    "资源恢复后": "恢复资源后",
    "资源消耗前": "消耗资源前",
    "资源消耗后": "消耗资源后",
    "资源变化后": "资源变化后",
    "添加状态前": "被添加状态前",
    "添加状态后": "被添加状态后",
    "添加状态失败后": "被添加状态失败后",
    "移除状态前": "被移除状态前",
    "移除状态后": "被移除状态后",
    "状态层数变化后": "状态层数变化后",
    "状态反应后": "状态反应后",
    "技能施放前": "施放技能前",
    "技能施放后": "施放技能后",
    "技能施放失败后": "施放技能失败后",
    "技能冷却完成后": "技能冷却完成时",
    "技能冷却变化后": "技能冷却变化后",
    "技能变化后": "技能变化后",
    "形态切换后": "形态切换后",
    "事件转化后": "事件转化后",
    "战场规则变化后": "战场规则变化后",
    "关联变化后": "关联变化后",
    "死亡后": "死亡后",
    "击杀后": "击杀后",
    "复活后": "复活后",
    "战斗对象入场后": "召唤物入场后",
    "战斗对象退场后": "召唤物退场后",
    "阵法展开": "阵法展开时",
    "阵法轮转后": "阵法轮转后",
    "阵法冲击后": "阵法冲击后",
    "阵法崩解后": "阵法崩解后",
    "地势承伤后": "地势承伤后",
    "地势变化前": "地势变化前",
    "地势变化后": "地势变化后",
}

#: 监听视角。
CAMP_PHRASES = {
    "自身": "自身",
    "其他己方": "其他己方",
    "任意己方": "任意己方",
    "任意敌方": "任意敌方",
    "任意": "任意角色",
}

#: 取目标时的范围说法。
RANGE_PHRASES = {
    "自身": "自身",
    "当前目标": "当前目标",
    "效果来源": "效果来源",
    "事件来源": "事件来源",
    "事件承受者": "事件承受者",
    "行动者": "行动者",
    "己方": "己方",
    "敌方": "敌方",
    "全体": "全体",
    "任意": "任意角色",
    "关联对象": "关联对象",
    "主人": "主人",
    "控制者": "控制者",
    "本编组主战者": "本编组主战者",
}

#: 可以数人头的范围；只有这些范围才写「一名 / N名」。
COUNTABLE = frozenset({"己方", "敌方", "全体", "任意", "关联对象", "本编组主战者"})

SORT_PHRASES = {
    "默认": "",
    "随机": "随机",
    "血气比例从低到高": "血气比例最低",
    "血气比例从高到低": "血气比例最高",
    "速度从高到低": "速度最高",
    "行动条从高到低": "行动条最前",
}

COMPARE_PHRASES = {
    "等于": "等于",
    "不等于": "不等于",
    "大于": "大于",
    "大于等于": "大于等于",
    "小于": "小于",
    "小于等于": "小于等于",
}

#: 二元计算的写法；乘方与取小/取大另有句式，不走这张表。
CALC_PHRASES = {
    "相加": "+",
    "相减": "−",
    "相乘": "×",
    "相除": "÷",
}

RESOURCE_PHRASES = {"血气": "血气", "精神": "精神", "护盾": "护盾"}

STATUS_CATEGORY_PHRASES = {"正面": "正面", "负面": "负面", "中性": "中性"}


#: 技能与处理段的序号。现有说明用圈码，渲染沿用。
ORDINALS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def _ordinal(index: int) -> str:
    return ORDINALS[index - 1] if 1 <= index <= len(ORDINALS) else f"{index}"


#: 丹药「用途」，与展示层既有说法保持一致。
USAGE_PHRASES = {
    "寄存战丹": "服用后备入战丹位，仅下一场正式战斗生效",
    "恢复精神": "服用后恢复精神",
    "恢复血气": "服用后恢复血气",
    "境界突破": "用于境界突破",
    "构筑重做": "重塑当前同行道侣的修行构筑",
    "突破补正": "补正人物或当前同行道侣的突破所得",
    "护持道契": "在铜雀台夺元时护持道契",
    "转变性别": "改变人物性别",
}

#: 丹药 `使用效果` 里除正文外的字段，沿用展示层既有的标签。
USAGE_LABELS = {
    "目标角色": "适用对象",
    "目标构筑": "重塑构筑",
    "候选来源": "重塑来源",
    "保持装配数量": "保持原有槽位数量",
    "补正来源": "补正来源",
    "选择数量": "选择数量",
    "只限纯突破节点": "仅限纯属性突破",
    "允许重复补正": "允许重复补正",
}

#: 已单独处理的 `使用效果` 字段。
USAGE_HANDLED = frozenset({"类型", "恢复百分比", "目标境界", "永久属性", "战前状态", "监听"})


def _number(value: object) -> str:
    """数值转文本：整数不写小数点，其他保留原始写法。"""

    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _percent(value: object) -> str:
    return f"{_number(value)}%"


def _join(items: Sequence[str], separator: str = "、") -> str:
    return separator.join(item for item in items if item)


def _plain(value: object) -> object:
    """把 mappingproxy 之类的只读容器摊成普通 dict/list。

    `ItemDetail.fields` 是 `MappingProxyType`，嵌套值也可能是只读视图，`json.dumps`
    直接吃会报 `Object of type mappingproxy is not JSON serializable`。
    """

    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_plain(item) for item in value]
    return value


def _fingerprint(value: object) -> str:
    """比较两段能力树是否一模一样，用来识别「成败分支同内容」这种写法。"""

    return json.dumps(_plain(value), ensure_ascii=False, sort_keys=True)


def _is_nodes(value: object) -> bool:
    """判断一个字段是能力节点还是普通值。"""

    return isinstance(value, Mapping) and isinstance(value.get("能力"), str)


#: 能力名（`定义/原子能力.json` 的数据键）→ 渲染方法名。
#:
#: **数据键是中文，方法名是英文**：数据层一律中文键，代码标识符一律英文（不是所有机器
#: 都吃得下中文标识符，而且中文变量名在 diff 里也难对齐）。所以 `_effect` 不拼方法名，
#: 查这张表。判据 `tools/架构审查/检查原子能力.py` 按它核对「登记的能力都有渲染路径」。
ABILITY_RENDERERS: dict[str, str] = {
    "读取数值": "_ability_read_value",
    "计算数值": "_ability_compute_value",
    "随机数值": "_ability_random_value",
    "聚合数值": "_ability_aggregate_value",
    "造成伤害": "_ability_deal_damage",
    "恢复资源": "_ability_restore_resource",
    "消耗资源": "_ability_spend_resource",
    "设置资源": "_ability_set_resource",
    "转移资源": "_ability_transfer_resource",
    "添加状态": "_ability_add_status",
    "移除状态": "_ability_remove_status",
    "修改状态层数": "_ability_change_status_stacks",
    "修改状态持续": "_ability_change_status_duration",
    "复制状态": "_ability_copy_status",
    "转移状态": "_ability_transfer_status",
    "修改行动条": "_ability_change_action_gauge",
    "修改技能冷却": "_ability_change_skill_cooldown",
    "修改构筑计量": "_ability_change_build_meter",
    "追加攻击": "_ability_extra_attack",
    "分摊伤害": "_ability_share_damage",
    "转移伤害": "_ability_transfer_damage",
    "抵挡致命伤害": "_ability_resist_lethal_damage",
    "复活": "_ability_revive",
    "修改事件数值": "_ability_modify_event_value",
    "修改事件目标": "_ability_modify_event_target",
    "修改事件标签": "_ability_modify_event_tags",
    "取消事件": "_ability_cancel_event",
    "支付代价": "_ability_pay_cost",
    "触发技能": "_ability_trigger_skill",
    "记录战斗事实": "_ability_record_combat_fact",
    "修改战斗关联": "_ability_modify_battle_relation",
    "修改技能": "_ability_modify_skill",
    "复制技能": "_ability_copy_skill",
    "修改行动意图": "_ability_modify_action_intent",
    "转化事件": "_ability_convert_event",
    "修改判定": "_ability_modify_check",
    "修改战场规则": "_ability_modify_battle_rule",
    "保存结果": "_ability_save_result",
    "切换形态": "_ability_switch_form",
    "创建战斗对象": "_ability_create_object",
    "移除战斗对象": "_ability_remove_object",
    "修改归属": "_ability_change_owner",
    "回放效果": "_ability_replay_effect",
    "修改战术": "_ability_modify_tactic",
    "固定属性加成": "_ability_fixed_attribute_bonus",
    "顺序执行": "_ability_sequence",
    "条件执行": "_ability_conditional",
    "随机执行": "_ability_random_branch",
    "遍历目标": "_ability_iterate_targets",
    "重复执行": "_ability_repeat",
    "尝试执行": "_ability_attempt",
    "事务执行": "_ability_transaction",
    "监听事件": "_ability_listen_event",
}

#: 条件名（`定义/原子能力.json` 里 `类别 = 条件` 的键）→ 渲染方法名。
CONDITION_RENDERERS: dict[str, str] = {
    "概率条件": "_condition_chance",
    "数值条件": "_condition_number",
    "状态条件": "_condition_status",
    "类型条件": "_condition_type",
    "标签条件": "_condition_tags",
    "组合条件": "_condition_group",
}


class CardText:
    """一张卡（或一枚战丹、一条伤势）的规则正文渲染器。"""

    def __init__(self, entity: Mapping[str, object]):
        self.entity = entity
        self.unknown: list[str] = []
        self.counters: dict[str, Mapping] = {}
        self.statuses: dict[str, Mapping] = {}
        #: 渲染节点时顺手记下的引擎级细节，由外层收进「明细」行。
        self._pending: list[str] = []
        self._collect_terms()

    def _defer(self, detail: str) -> None:
        """把引擎级细节挂到外层，正文里不写。"""

        self._pending.append(detail)

    def _drain(self) -> list[str]:
        pending, self._pending = self._pending, []
        return pending

    # —— 词条登记 ——————————————————————————————————————————————

    def _collect_terms(self) -> None:
        for node in self._walk(self.entity):
            if node.get("能力") == "修改构筑计量" and isinstance(node.get("计量"), str):
                self.counters.setdefault(str(node["计量"]), node)
            elif node.get("能力") == "添加状态":
                holder = node.get("状态")
                if isinstance(holder, Mapping) and isinstance(holder.get("名称"), str):
                    self.statuses.setdefault(str(holder["名称"]), holder)

    @staticmethod
    def _walk(node: object):
        if isinstance(node, Mapping):
            yield node
            for value in node.values():
                yield from CardText._walk(value)
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes)):
            for value in node:
                yield from CardText._walk(value)

    def _flag(self, kind: str, detail: str) -> str:
        """认不出来的东西留痕，交给审查工具报错。"""

        self.unknown.append(f"{kind}：{detail}")
        return f"〈未支持：{detail}〉"

    def _fallback(self, label: str, text_: str) -> str:
        """**解释层兜底**：数据里没写、渲染器自己补了一个说法。

        负责人口径（第 75 轮）：描述必须与设计一模一样，**不许在解释层兜底**。
        所以这里照旧渲染出一个能读的句子（卡面不至于开天窗），但**必须留痕**——
        `渲染正文对照` 与 `检查重复动作` 都拿 `unknown` 当判据，兜底一多就会红。
        真正该做的是回数据里把那一段补上，而不是让渲染器猜。
        """

        self.unknown.append(f"兜底：{label}")
        return text_

    # —— 入口 ——————————————————————————————————————————————

    def body(self) -> tuple[str, ...]:
        """返回规则正文的行；卡头风味简介不在这里。"""

        # 战场环境不走 `能力`：它按阶段推进，每阶段有入阶效果与常驻监听。
        stages = self.entity.get("阶段")
        if isinstance(stages, Sequence) and not isinstance(stages, (str, bytes)) and stages:
            return self._stages(stages)

        # 丹药也不走 `能力`：规则挂在 `使用效果.监听` 上。
        abilities = self.entity.get("能力")
        if not isinstance(abilities, Sequence) or isinstance(abilities, (str, bytes)) or not abilities:
            effect = self.entity.get("使用效果")
            if isinstance(effect, Mapping):
                return self._usage(effect)
            return ()

        actives = [item for item in abilities if item.get("能力") == "主动技能"]
        if not isinstance(abilities, Sequence) or isinstance(abilities, (str, bytes)):
            return ()
        actives = [item for item in abilities if item.get("能力") == "主动技能"]
        passives = [item for item in abilities if item.get("能力") == "被动技能"]
        statics = [item for item in abilities if item.get("能力") == "固定属性加成"]
        others = [
            item
            for item in abilities
            if item.get("能力") not in ("主动技能", "被动技能", "固定属性加成")
        ]
        for item in others:
            self._flag("构筑根能力", str(item.get("能力")))

        lines: list[str] = []
        if actives:
            lines.append("主动：")
            for index, skill in enumerate(actives, 1):
                lines.extend(self._skill(index, skill))
        if passives:
            # 一个被动只挂一条监听（`拆被动.py`）。读本卡计量的那类监听归「裁定」段，
            # 于是有些被动在正文里一句都没有——那就**整条不列**，并且把编号重新连起来，
            # 免得出现「③[] 空着」这种断号（实测拆完之后就有一堆）。
            visible = [(skill, self._passive_body(skill)) for skill in passives]
            visible = [(skill, body) for skill, body in visible if body]
            if visible:
                lines.append("被动：")
                for index, (skill, body) in enumerate(visible, 1):
                    lines.append(f"{_ordinal(index)}[{self._short_name(skill.get('名称'))}]")
                    lines.extend(body)
        if statics and not actives and not passives:
            # 气机整张卡只有固定属性加成，没有主动/被动可分，所以不另起小节标题——
            # 「契合」这个词直接当句子主语用，四类方向各叫各的。
            return self._affinity(statics)
        if statics:
            lines.extend(self._statics(statics))
        rulings = self._rulings(passives)
        if rulings:
            lines.append("裁定：")
            lines.extend(rulings)
        return tuple(lines)

    def _affinity(self, nodes: Sequence[Mapping]) -> list[str]:
        """气机：契合一条，只写固定属性加成，不谈过程。"""

        parts: list[str] = []
        for node in nodes:
            attributes = node.get("属性")
            if not isinstance(attributes, Mapping):
                parts.append(self._flag("固定属性加成", "缺少属性"))
                continue
            parts.extend(
                self._attribute_change(key, value) for key, value in attributes.items()
            )
        return [f"契合：{'、'.join(parts)}"] if parts else []

    # —— 装配层 ——————————————————————————————————————————————

    def _skill(self, index: int, skill: Mapping) -> list[str]:
        """一条主动技能。写法见 `说明模版.md`：

        `①[破格]：耗神17，冷却2行动。` 然后效果按「整句 + • 分条」排。
        """

        name = self._short_name(skill.get("名称"))
        title = [f"耗神{_number(skill['精神消耗'])}"] if "精神消耗" in skill else []
        if "冷却行动" in skill:
            title.append(f"冷却{_number(skill['冷却行动'])}行动")
        lines = [f"{_ordinal(index)}[{name}]：" + ("，".join(title) + "。" if title else "")]
        condition = []
        attempt = skill.get("使用次数")
        if attempt is not None:
            condition.append(f"整场最多施展{_number(attempt)}次")
        if condition:
            lines.append("；".join(condition) + "。")
        trigger = self._activation(skill)
        if trigger:
            lines.append("发动：" + trigger + "。")
        lines.extend(self._sequence(skill.get("效果")))
        detail = self._drain() + self._skill_detail(skill)
        if detail:
            lines.append("明细：" + " · ".join(detail))
        return lines

    def _short_name(self, value: object) -> str:
        """技能名在 JSON 里是 `卡名·短名`，文本里只写短名。"""

        text = str(value or "")
        if not text:
            return self._fallback("能力缺名称", "未命名")
        return text.rsplit("·", 1)[-1]

    def _activation(self, skill: Mapping) -> str:
        parts: list[str] = []
        cost = skill.get("额外代价")
        if _is_nodes(cost):
            parts.append(self._effect(cost))
        return "；".join(part for part in parts if part)

    def _skill_detail(self, skill: Mapping) -> list[str]:
        detail: list[str] = []
        if skill.get("共享冷却"):
            detail.append("与其他技能共享冷却")
        if skill.get("失败时回滚"):
            detail.append("任一环节不成立则整段回滚")
        # 技能标签（单体/群体/连击…）不再写进卡面：卡片归哪一类由目录说清楚了
        # （`功法-丹诀.json` 就是分类），标签只在引擎内部当条件用（`标签条件`）。
        return detail

    def _passive_body(self, skill: Mapping) -> list[str]:
        """一条被动的内容（不含 `①[名字]` 那行；标题由调用方按可见条数编号）。"""

        lines: list[str] = []
        for node in skill.get("效果") or ():
            if not isinstance(node, Mapping) or node.get("能力") != "监听事件":
                self._flag("被动技能.效果", str(node.get("能力") if isinstance(node, Mapping) else node))
                continue
            # 读本卡计量、并且**带阈值**的监听属于结算段，单独放进「裁定」，不在被动里重复。
            if self._verdict_node(node) is not None:
                continue
            lines.extend(self._listener(node))
        return lines

    def _listener(self, node: Mapping) -> list[str]:
        """一条被动监听。写法见 `说明模版.md`：

        触发条件独立成行；触发上限**单独成行、置于效果之前**（原来挤在「明细」里）；
        效果按「依次执行：」+ `•` 分条。
        """

        lines = [self._trigger(node) + "，依次执行："]
        caps = self._listener_caps(node)
        if caps:
            lines.append("；".join(caps) + "。")
        lines.extend(self._sequence(node.get("效果")))
        detail = self._drain() + self._listener_detail(node, caps=True)
        if detail:
            lines.append("明细：" + " · ".join(detail))
        return lines

    def _trigger(self, node: Mapping) -> str:
        event = str(node.get("事件") or "")
        phrase = EVENT_PHRASES.get(event)
        if phrase is None:
            phrase = self._flag("事件", event)
        camp = CAMP_PHRASES.get(str(node.get("阵营关系") or ""), str(node.get("阵营关系") or ""))
        text = f"每当{camp}{phrase}"
        extra = node.get("条件")
        if extra:
            text += "，且" + self._conditions(extra)
        return text

    def _listener_caps(self, node: Mapping) -> list[str]:
        """触发上限：按模版单独成行、放在效果之前。"""

        caps: list[str] = []
        if node.get("每场战斗最多触发") is not None:
            caps.append(f"每场战斗最多触发{_number(node['每场战斗最多触发'])}次")
        if node.get("每次行动最多触发") is not None:
            caps.append(f"每行动最多结算{_number(node['每次行动最多触发'])}次")
        return caps

    def _listener_detail(self, node: Mapping, *, caps: bool = False) -> list[str]:
        detail: list[str] = []
        if not caps:
            if node.get("每次行动最多触发") is not None:
                detail.append(f"每行动只能使用{_number(node['每次行动最多触发'])}次")
            if node.get("每场战斗最多触发") is not None:
                detail.append(f"每场战斗只能使用{_number(node['每场战斗最多触发'])}次")
        if node.get("优先级") is not None:
            detail.append(f"优先级{_number(node['优先级'])}")
        return detail

    def _usage(self, effect: Mapping) -> list[str]:
        """丹药：用途 → 战前生效 → 监听正文。"""

        lines: list[str] = []
        kind = str(effect.get("类型") or "")
        if kind:
            lines.append("用途：" + USAGE_PHRASES.get(kind, kind))
        if effect.get("恢复百分比") is not None:
            lines.append(f"恢复：{_percent(effect['恢复百分比'])}")
        prepared = effect.get("战前状态")
        if isinstance(prepared, Mapping):
            lines.append("战前生效：" + self._prepared_status(prepared))
        for node in effect.get("监听") or ():
            if isinstance(node, Mapping) and node.get("能力") == "监听事件":
                lines.extend(self._listener(node))
            else:
                ability = node.get("能力") if isinstance(node, Mapping) else node
                lines.append(self._flag("丹药.监听", str(ability)))
        for key, value in effect.items():
            if key in USAGE_HANDLED:
                continue
            lines.append(f"{USAGE_LABELS.get(str(key), str(key))}：{self._scalar(value)}")
        return lines

    def _prepared_status(self, holder: Mapping) -> str:
        """战丹的战前状态：整场战斗生效，写在开打之前。"""

        parts: list[str] = []
        if holder.get("持续单位") == "整场战斗":
            parts.append("整场战斗")
        elif holder.get("剩余行动") is not None:
            parts.append(f"持续{_number(holder['剩余行动'])}次行动")
        attributes = holder.get("属性")
        if isinstance(attributes, Mapping) and attributes:
            parts.append(
                "、".join(self._attribute_change(key, value) for key, value in attributes.items())
            )
        return f"获得[{holder.get('名称')}]" + (f"（{'、'.join(parts)}）" if parts else "")

    def _scalar(self, value: object) -> str:
        if isinstance(value, bool):
            return "是" if value else "否"
        if isinstance(value, (int, float)):
            return _number(value)
        if isinstance(value, str):
            return value
        return json.dumps(_plain(value), ensure_ascii=False)

    def _stages(self, stages: Sequence[Mapping]) -> list[str]:
        """战场环境：按阶段推进，每阶段写入阶效果与常驻监听。"""

        lines = ["阶段："]
        for index, stage in enumerate(stages, 1):
            if not isinstance(stage, Mapping):
                lines.append(self._flag("战场环境.阶段", str(stage)))
                continue
            title = f"{_ordinal(index)}[{stage.get('名称')}]"
            ratio = stage.get("起始承伤比例")
            if ratio is not None:
                title += f"　起始承伤{_percent(round(float(ratio) * 100))}"
            lines.append(title)
            entry = stage.get("入阶能力")
            if isinstance(entry, Sequence) and not isinstance(entry, (str, bytes)) and entry:
                lines.append("入阶：" + self._block(entry) + "。")
                detail = self._drain()
                if detail:
                    lines.append("明细：" + " · ".join(detail))
            for node in stage.get("常驻能力") or ():
                if isinstance(node, Mapping) and node.get("能力") == "监听事件":
                    lines.extend(self._listener(node))
                else:
                    ability = node.get("能力") if isinstance(node, Mapping) else node
                    lines.append(self._flag("战场环境.常驻能力", str(ability)))
        return lines

    def _statics(self, nodes: Sequence[Mapping]) -> list[str]:
        lines = ["常驻："]
        for node in nodes:
            attributes = node.get("属性")
            if not isinstance(attributes, Mapping):
                lines.append("　" + self._flag("固定属性加成", "缺少属性"))
                continue
            changes = []
            for key, value in attributes.items():
                number = float(value)
                sign = "+" if number >= 0 else "−"
                changes.append(f"{key}{sign}{_number(abs(number))}")
            lines.append("　永久获得：" + _join(changes))
        return lines

    # —— 裁定 ——————————————————————————————————————————————

    def _rulings(self, passives: Sequence[Mapping]) -> list[str]:
        """计量结算段。按 `说明模版.md` 写成三段：

        `自身行动结束时检查。` / `[X]达到9时：` / `•效果…` / 结算限制一行。
        """

        lines: list[str] = []
        if not self.counters:
            return lines
        seen: set[str] = set()
        index = 1
        for skill in passives:
            for node in skill.get("效果") or ():
                if not isinstance(node, Mapping) or node.get("能力") != "监听事件":
                    continue
                verdict = self._verdict_node(node)
                if verdict is None:
                    continue
                names, threshold = verdict
                key = f"{skill.get('名称')}:{node.get('事件')}:{','.join(sorted(names))}"
                if key in seen:
                    continue
                seen.add(key)
                lines.append(f"{_ordinal(index)}[{_join(sorted(names))}]")
                lines.append(self._trigger(node) + "检查。")
                lines.append(f"[{_join(sorted(names))}]达到{threshold}时：")
                lines.extend(self._counter_check(node, sorted(names), threshold))
                caps = self._listener_caps(node)
                limits = self._counter_limits(sorted(names))
                tail = caps + limits
                if tail:
                    lines.append("；".join(tail) + "。")
                index += 1
        return lines

    def _verdict_node(self, node: object) -> tuple[set[str], str] | None:
        """这条监听是不是「某个计量达到 N 就结算」；是的话给出（计量们, N）。

        **不是「读了计量就算裁定」**：有的监听只是把计量值记进历史（`记录战斗事实` 里读
        一下），它没有阈值，按裁定渲染就会写出「达到条件满足」——那是解释层兜底
        （第 75 轮实测 6 处）。没有阈值的监听留在它自己的被动里照常渲染。
        """

        names: set[str] = set()
        for child in self._walk(node):
            if child.get("能力") != "数值条件":
                continue
            left = child.get("左值")
            if not isinstance(left, Mapping):
                continue
            matched = {
                name_
                for sub in self._walk(left)
                if sub.get("能力") == "读取数值" and sub.get("来源") == "构筑计量"
                for name_ in (sub.get("计量"),)
                if isinstance(name_, str) and name_ in self.counters
            }
            if not matched:
                continue
            right = child.get("右值")
            if right is None:
                continue
            names |= matched
            return names, self._value(right)
        return None

    def _threshold(self, node: Mapping) -> str:
        """取「达到几」（阈值条件可能嵌在 `成立效果` 里，所以整棵子树里找）。

        只用来给 `_is_threshold_guard` 比对「这句是不是外层那句话的重复写法」；
        正文里的阈值由 `_verdict_node` 直接给出，这里取不到就返回空串（不兜底）。
        """

        for condition in self._walk(node):
            if condition.get("能力") != "数值条件":
                continue
            right = condition.get("右值")
            if isinstance(right, (int, float)):
                return _number(right)
        return ""

    def _counter_check(self, node: Mapping, names: list[str], threshold: str) -> list[str]:
        """裁定段的达标效果。

        外层已经写了「[X]达到9时：」，所以里层那个 `若[X]大于等于9` 是**重复条件**，
        按模版要把成立效果直接摊成 `•` 条目，不能再套一层「若…则…」。

        `尝试执行` 若「成功效果」与「失败效果」同内容（引擎里表达「无论如何都做」
        的唯一写法），模版把尝试步骤与这条合并成几条 `•`——避免在裁定段里铺出
        「尝试依次执行：/ 无论成败，都执行：」两层嵌套。
        """

        lines: list[str] = []
        for child in node.get("效果") or ():
            if not isinstance(child, Mapping):
                continue
            if str(child.get("能力") or "") == "条件执行" and self._is_threshold_guard(
                child, names, threshold
            ):
                lines.extend(self._ruling_branch(self._branch(child.get("成立效果"))))
                continue
            lines.extend(self._ruling_branch([child]))
        return lines if lines else self._sequence(node.get("效果"))

    def _ruling_branch(self, nodes: list) -> list[str]:
        """裁定段的分支：摊成 `•`。

        `尝试执行` 的两分支同内容时（引擎里表达「无论如何都要执行」的唯一写法），
        那一步**只写一条**——原来会写成两条一模一样的「清零」，读起来像重复动作。
        """

        out: list[str] = []
        for item in nodes:
            if not isinstance(item, Mapping):
                continue
            if str(item.get("能力") or "") != "尝试执行":
                out.extend(self._sequence([item]))
                continue
            out.extend(self._sequence(self._branch(item.get("尝试效果"))))
            success = item.get("成功效果")
            failure = item.get("失败效果")
            out.extend(self._sequence(self._branch(success)))
            if not (failure is not None and _fingerprint(success) == _fingerprint(failure)):
                out.extend(self._sequence(self._branch(failure)))
        return self._collapse_always(out)

    def _collapse_always(self, lines: list[str]) -> list[str]:
        """把「无论成败」重复的同一条描述收成一条。

        引擎用「成功/失败分支同内容」表达「始终执行」，照抄就会在卡面上出现两条
        一模一样的 `•`。这里按行文本去重相邻重复项。
        """

        out: list[str] = []
        for line in lines:
            if out and out[-1] == line:
                continue
            out.append(line)
        return out

    def _is_threshold_guard(self, node: Mapping, names: list[str], threshold: str) -> bool:
        """这个 `条件执行` 是否就是外层那句「达到 N」的重复写法。"""

        conditions = node.get("条件")
        if not isinstance(conditions, Sequence) or isinstance(conditions, (str, bytes)):
            return False
        for condition in conditions:
            if not isinstance(condition, Mapping) or condition.get("能力") != "数值条件":
                return False
            left = condition.get("左值")
            if not isinstance(left, Mapping):
                return False
            name = left.get("计量") if left.get("来源") == "构筑计量" else left.get("状态")
            if name not in names:
                return False
            right = condition.get("右值")
            if not isinstance(right, (int, float)) or _number(right) != threshold:
                return False
        return True

    def _counter_limits(self, names: Sequence[str]) -> list[str]:
        """结算限制：上限 + 清零语。

        按 `说明模版.md` 写成一行：`[X]上限100；清零后必须重新积累。`
        """

        lines: list[str] = []
        for name in names:
            holder = self.counters.get(name) or {}
            cap = holder.get("最高值")
            if cap is not None:
                lines.append(f"[{name}]上限{_number(cap)}")
        if lines:
            lines.append("清零后必须重新积累")
        return lines

    def _read_counters(self, node: object) -> set[str]:
        names: set[str] = set()
        for child in self._walk(node):
            if child.get("能力") == "读取数值" and child.get("来源") == "构筑计量":
                name = child.get("计量")
                if isinstance(name, str) and name in self.counters:
                    names.add(name)
        return names

    # —— 组合 ——————————————————————————————————————————————

    def _effects(self, nodes: object) -> str:
        """效果数组按 `；然后` 连接——数组顺序就是结算顺序。"""

        if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
            return self._flag("效果", "不是数组")
        parts = [self._effect(node) for node in nodes]
        return "；然后".join(part for part in parts if part)

    def _block(self, nodes: object, *, separator: str = "；然后") -> str:
        """嵌套效果块用圆括号包起来。

        顶层步骤之间已经是 `；然后`，嵌套块如果也用 `；` 就会读不出层级，
        玩家分不清哪一步在条件里面。
        """

        if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
            return self._flag("效果块", "不是数组")
        parts = [self._effect(node) for node in nodes]
        body = separator.join(part for part in parts if part)
        return f"（{body}）" if len(parts) > 1 else body

    # —— 分段层：按 `说明模版.md` 把效果排成「整句 + • 分条」 ————————————

    #: 需要单独成段（而不是挤进一行）的组合能力。
    _BLOCK_ABILITIES = frozenset(
        {"随机执行", "事务执行", "遍历目标", "遍历", "条件执行", "尝试执行"}
    )

    def _sequence(self, nodes: object, *, prefix: str = "", inline: bool = False) -> list[str]:
        """把一串效果排成多行：组合能力各成一段，连续同类动作合成一条。

        `说明模版.md` 的书写约定：每个独立结算动作用 `•` 单独一条；同一触发时机、
        同一目标的连续计量增加可合并（`[裂岳锋痕]+23`）。不这么做就会读成
        一行十几个「；然后」，正是原来的问题。

        `inline=True` 用于**条件/尝试分支内部**：那里要的是紧凑的一行，而不是分条。
        """

        if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
            return [self._flag("效果", "不是数组")]
        if inline:
            return ["•" + prefix + self._effects(nodes) + "；"]
        lines: list[str] = []
        index = 0
        while index < len(nodes):
            node = nodes[index]
            index += 1
            if not isinstance(node, Mapping):
                lines.append("•" + self._flag("效果", str(node)) + "；")
                continue
            ability = str(node.get("能力") or "")
            if ability == "随机执行":
                lines.extend(self._random_section(node, prefix=prefix))
                # 模版：随机块之后若还有同级效果，**另起一段**写明「随机效果结算后」，
                # 而不是把它塞成随机块里的一条 `•`。
                trailing = nodes[index:]
                if trailing:
                    lines.append(f"{prefix}随机效果结算后，依次执行：")
                    for item in trailing:
                        if isinstance(item, Mapping):
                            lines.append("•" + self._effect(item) + "；")
                        else:
                            lines.append("•" + self._flag("效果", str(item)) + "；")
                    break
                continue
            if ability == "顺序执行":
                lines.extend(self._sequence(node.get("效果"), prefix=prefix))
            elif ability in self._BLOCK_ABILITIES:
                lines.extend(self._block_section(node, prefix=prefix))
            elif self._has_block_inside(node):
                # 本身是叶子，但体内（条件/尝试/随机）还有组合段或多个动作：先摊引导句，
                # 再让内层自己展开，不能在外面盖一个 `•` 把它压回一行。
                lines.append(self._effect(node).rstrip("。；") + "，则：")
                lines.extend(self._sequence(self._inner_nodes(node), prefix=prefix))
            else:
                lines.append("•" + prefix + self._effect(node) + "；")
        return lines

    #: 装着「一串动作」的字段名——`_inner_nodes` 只看这些，避免把目标/状态定义也
    #: 当成独立步骤（那样 `选择目标` 会被单独渲染成一条，实测炸出 4781 处未支持）。
    _ACTION_KEYS = ("效果", "尝试效果", "成功效果", "失败效果", "成立效果", "不成立效果", "条件效果")

    def _inner_nodes(self, node: Mapping) -> list:
        """叶子体内还嵌着的动作（用于把它摊成引导句 + 分条）。

        只看 `_ACTION_KEYS` 里那几种「一串动作」的字段；`顺序执行` 继续拆开成它的子项，
        否则「尝试效果=顺序执行[4 步]」会被当成一整块，判定不出「体内需要分条」，
        那 4 步就又被压回一行。
        """

        out: list = []

        def visit(value: object) -> None:
            if isinstance(value, Mapping):
                if str(value.get("能力")) == "顺序执行":
                    inner = value.get("效果")
                    if isinstance(inner, Sequence) and not isinstance(inner, (str, bytes)):
                        for child in inner:
                            visit(child)
                        return
                if isinstance(value.get("能力"), str):
                    out.append(value)
                    return
                for child in value.values():
                    visit(child)
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                for child in value:
                    visit(child)

        for key in self._ACTION_KEYS:
            visit(node.get(key))
        return [item for item in out if item is not node]

    def _has_block_inside(self, node: Mapping) -> bool:
        """这个叶子体内是否该摊成引导句 + 分条。

        体内有组合段（条件/尝试/随机/遍历）**或**有多个动作时都算——多个动作摊成
        `•` 条目正是模版的要求。
        """

        inner = self._inner_nodes(node)
        if len(inner) > 1:
            return True
        for child in inner:
            if isinstance(child, Mapping) and str(child.get("能力") or "") in self._BLOCK_ABILITIES:
                return True
        return False

    def _random_section(self, node: Mapping, *, prefix: str = "") -> list[str]:
        """`随机执行` 自成一段：引导句 + `•` 逐项。"""

        options = node.get("选项") or []
        way = "不重复" if node.get("是否放回") is False else ""
        lines = [
            f"{prefix}释放时，从以下{_number(len(options))}项中{way}"
            f"随机触发{_number(node.get('抽取数量'))}项："
        ]
        for option in options:
            lines.append("•" + self._effect(option) + "；")
        return lines

    def _block_section(self, node: Mapping, *, prefix: str = "") -> list[str]:
        """一个组合能力自成一段：引导句 + `•` 分条。"""

        ability = str(node.get("能力") or "")
        if ability == "随机执行":
            options = node.get("选项") or []
            way = "不重复" if node.get("是否放回") is False else ""
            head = f"{prefix}释放时，从以下{_number(len(options))}项中{way}随机触发{_number(node.get('抽取数量'))}项："
            lines = [head]
            for option in options:
                lines.append("•" + self._effect(option) + "；")
            return lines
        if ability == "事务执行":
            return self._transaction(node, prefix=prefix)
        if ability in ("遍历目标", "遍历"):
            target = self._target(node.get("目标"))
            lines = [f"{prefix}对{target}逐个结算："]
            inner = node.get("效果")
            if isinstance(inner, Sequence) and not isinstance(inner, (str, bytes)):
                for item in inner:
                    lines.append("•" + self._effect(item) + "；")
            return lines
        if ability == "条件执行":
            # 「若〈判据〉则：」+ 成立效果分条；不成立再起一句。
            # 分支里的项**继续走 `_sequence`**，嵌套的组合段才会各自展开，不会被压平。
            conditions = node.get("条件")
            judge = self._conditions(conditions) if conditions else ""
            if judge:
                head = f"{prefix}若{judge}，则依次执行："
            else:
                # 没写条件就没得判：引擎侧「空条件」恒成立，正文不能顺势写成「若成立」
                # （那是解释层兜底）。
                head = f"{prefix}{self._fallback('条件执行缺条件', '若成立')}，则依次执行："
            lines = [head]
            lines.extend(self._sequence(self._branch(node.get("成立效果")), prefix=prefix))
            fallback = self._branch(node.get("不成立效果"))
            if fallback:
                lines.append(f"{prefix}若不成立，则依次执行：")
                lines.extend(self._sequence(fallback, prefix=prefix))
            return lines
        if ability == "尝试执行":
            lines = [f"{prefix}尝试依次执行："]
            lines.extend(self._sequence(self._branch(node.get("尝试效果")), prefix=prefix))
            success = node.get("成功效果")
            failure = node.get("失败效果")
            if failure is not None and _fingerprint(success) == _fingerprint(failure):
                # 引擎里唯一能表达「无论如何都做某件事」的写法，文本上收成一句。
                lines.append(f"{prefix}无论成败，都执行：")
                lines.extend(self._sequence(self._branch(success), prefix=prefix))
                return lines
            ok = self._branch(success)
            if ok:
                lines.append(f"{prefix}若能完成，则：")
                lines.extend(self._sequence(ok, prefix=prefix))
            bad = self._branch(failure)
            if bad:
                lines.append(f"{prefix}若不能完成，则：")
                lines.extend(self._sequence(bad, prefix=prefix))
            return lines
        return ["•" + prefix + self._effect(node) + "；"]

    @staticmethod
    def _branch(nodes: object) -> list:
        """分支效果统一取成列表（`顺序执行` 拆开，其余原样）。"""

        if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
            return []
        if len(nodes) == 1 and isinstance(nodes[0], Mapping) \
                and str(nodes[0].get("能力") or "") == "顺序执行":
            inner = nodes[0].get("效果")
            if isinstance(inner, Sequence) and not isinstance(inner, (str, bytes)):
                return list(inner)
        return list(nodes)

    def _transaction(self, node: Mapping, *, prefix: str = "") -> list[str]:
        """`事务执行`：一条「连续执行」段，失败时整段回滚。"""

        name = str(node.get("名称") or "").strip()
        head = f"{prefix}随后连续执行[{name}]：" if name else f"{prefix}随后连续执行："
        lines = [head]
        for item in node.get("效果") or ():
            lines.append("•" + self._effect(item) + "；")
        failure = node.get("失败效果")
        if failure:
            lines.append(f"{prefix}若任一环节未完成，本次连续执行的消耗、计量和伤害全部回滚：")
            for item in failure:
                lines.append("•" + self._effect(item) + "；")
        return lines

    def _effect(self, node: object) -> str:
        if not isinstance(node, Mapping):
            return self._flag("效果", str(node))
        ability = str(node.get("能力") or "")
        name = ABILITY_RENDERERS.get(ability)
        handler = getattr(self, name, None) if name else None
        if handler is None:
            return self._flag("原子能力", ability)
        return handler(node)

    def _conditions(self, nodes: object) -> str:
        if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
            return self._flag("条件", "不是数组")
        if len(nodes) == 1:
            return self._condition(nodes[0])
        return "且".join(self._condition(node) for node in nodes)

    def _condition(self, node: object) -> str:
        if not isinstance(node, Mapping):
            return self._flag("条件", str(node))
        ability = str(node.get("能力") or "")
        name = CONDITION_RENDERERS.get(ability)
        handler = getattr(self, name, None) if name else None
        if handler is None:
            return self._flag("条件能力", ability)
        return handler(node)

    def _value(self, node: object) -> str:
        """数值位置：能力节点走渲染，裸值直接写。

        序列与映射**不能直接 `str()`**：那会把 `('烙印',)`、`{'行动': …}`、
        `mappingproxy(…)` 这些 **Python 内部表现的 `repr`** 印到卡面上；而且同一个值
        在不同读取路径下包装不同（`MappingProxy` 还是展开深拷贝后的普通字典），正文
        就跟着变。序列按中文顿号连写，映射写成 `‹键=值›`。
        """

        if _is_nodes(node):
            return self._effect(node)
        if isinstance(node, (int, float)) and not isinstance(node, bool):
            return _number(node)
        if isinstance(node, Mapping):
            return "‹" + "、".join(f"{key}={self._value(value)}" for key, value in node.items()) + "›"
        if isinstance(node, (list, tuple)):
            return "、".join(self._value(item) for item in node)
        return str(node)

    # —— 目标 ——————————————————————————————————————————————

    def _target(self, node: object) -> str:
        if node is None:
            # 引擎的缺省：`目标` / `归属` / `接收目标` 省略 = 「当前目标」
            # （`mechanics.DEFAULT_TARGET_SCOPE`，一处声明；这里读同一个常量，不另写字面量）。
            return RANGE_PHRASES.get(DEFAULT_TARGET_SCOPE, DEFAULT_TARGET_SCOPE)
        if not _is_nodes(node):
            return self._value(node)
        ability = str(node.get("能力"))
        if ability == "选择目标":
            return self._select_target(node)
        if ability == "选择技能":
            return self._select_skill(node)
        if ability == "选择状态":
            return self._select_status(node)
        return self._effect(node)

    def _select_target(self, node: Mapping) -> str:
        raw = str(node.get("范围") or "")
        phrase = RANGE_PHRASES.get(raw)
        if phrase is None:
            phrase = self._flag("选择目标.范围", raw)
        count = node.get("数量")
        if node.get("选择全部"):
            base = f"{phrase}全体" if raw in COUNTABLE - {"全体"} else phrase
        elif count is not None and raw in COUNTABLE:
            base = f"一名{phrase}" if float(count) == 1 else f"{_number(count)}名{phrase}"
        elif raw in COUNTABLE:
            # `数量` 省略时引擎取**一个**（`max(1, 数量 or 1)`），所以正文写「一名」。
            # 不写就成了「敌方」，读起来像整方——实测 `修改归属` 因此写成
            # 「将敌方的阵营改到‹己方›」，实际只改一个。
            base = f"一名{phrase}"
        else:
            base = phrase
        extras: list[str] = []
        life = node.get("生存状态")
        if life not in (None, "任意"):
            extras.append(str(life))
        kind = node.get("对象类型")
        if kind not in (None, "任意"):
            extras.append(str(kind))
        if node.get("排除自身"):
            extras.append("不含自身")
        identity = node.get("身份")
        if identity:
            extras.append(str(identity))
        owned = node.get("拥有状态")
        if owned:
            extras.append(f"拥有[{owned}]")
        if node.get("关联"):
            extras.append(f"关联：{node['关联']}")
        sort = SORT_PHRASES.get(str(node.get("排序") or "默认"), "")
        if sort:
            extras.append(sort)
        if node.get("选择全部") and count is not None:
            extras.append(f"最多{_number(count)}名")
        return base + ("（" + _join(extras) + "）" if extras else "")

    def _select_skill(self, node: object) -> str:
        # 同 `_select_status`：引擎只认「选择技能」节点，裸名字是数据错，要报出来。
        if not isinstance(node, Mapping):
            return self._flag("技能字段不是选择技能", str(node))
        # 引擎的缺省：`范围` 省略按「全部技能」（`mechanics._skills_select`）。
        raw = str(node.get("范围") or "全部技能")
        base = {
            "全部技能": "全部技能",
            "可用技能": "可用技能",
            "冷却中的技能": "冷却中的技能",
            "当前技能": "当前技能",
            "指定技能": f"[{node.get('名称')}]",
        }.get(raw)
        if base is None:
            base = self._flag("选择技能.范围", raw)
        if node.get("选择全部"):
            return f"{base}全体"
        sort = {
            "无": "",
            "随机": "随机一门",
            "冷却从低到高": "冷却最短的一门",
            "冷却从高到低": "冷却最长的一门",
            "释放顺序": "释放顺序最前的一门",
        }.get(str(node.get("排序") or "无"), "")
        if sort:
            return f"{sort}{base}"
        if node.get("数量") is not None:
            return f"{_number(node['数量'])}门{base}"
        return base

    def _select_status(self, node: object) -> str:
        # 引擎只认「选择状态」节点（`mechanics._select_statuses` 见到别的就返回空，
        # 也就是这个动作什么都不做）。写成裸名字是**数据错**，渲染要报出来而不是补个
        # 「状态」了事——那正是「解释层兜底」。
        if not isinstance(node, Mapping):
            return self._flag("状态字段不是选择状态", str(node))
        owner = self._target(node.get("目标"))
        parts = [f"{owner}的"]
        name = node.get("名称")
        if name:
            parts.append(f"[{name}]")
        category = node.get("分类")
        if category:
            parts.append(f"{STATUS_CATEGORY_PHRASES.get(str(category), str(category))}状态")
        labels = node.get("标签")
        if isinstance(labels, Sequence) and not isinstance(labels, (str, bytes)) and labels:
            parts.append("、".join(f"[{item}]" for item in labels))
        sort = {
            "获得顺序": "",
            "层数从高到低": "层数最多",
            "剩余行动从少到多": "剩余行动最少",
        }.get(str(node.get("排序") or "获得顺序"), "")
        text = "".join(parts)
        extras = [item for item in (sort,) if item]
        if node.get("选择全部"):
            extras.append("全部")
        elif node.get("数量") is not None:
            extras.append(f"最多{_number(node['数量'])}个")
        return text + ("（" + _join(extras) + "）" if extras else "")

    # —— 条件 ——————————————————————————————————————————————

    def _condition_chance(self, node: Mapping) -> str:
        return f"有{self._value(node.get('概率'))}%概率"

    def _condition_number(self, node: Mapping) -> str:
        left = self._value(node.get("左值"))
        right = self._value(node.get("右值"))
        compare = COMPARE_PHRASES.get(str(node.get("比较") or ""), str(node.get("比较") or ""))
        return f"{left}{compare}{right}"

    def _condition_status(self, node: Mapping) -> str:
        owner = self._target(node.get("目标"))
        compare = COMPARE_PHRASES.get(str(node.get("比较") or ""), str(node.get("比较") or ""))
        stacks = node.get("层数")
        prefix = f"{owner}的[{node.get('状态')}]"
        return f"{prefix}层数{compare}{_number(stacks)}" if compare else prefix

    def _condition_type(self, node: Mapping) -> str:
        # 引擎的缺省：`对象` 省略按「目标」（`mechanics._condition_type`），所以正文照写。
        raw = str(node.get("对象") or "")
        if not raw:
            return f"目标是{node.get('值')}"
        side = {"来源": "来源", "目标": "目标"}.get(raw)
        if side is None:
            side = self._fallback("类型条件对象不认识", "目标")
        return f"{side}是{node.get('值')}"

    def _condition_tags(self, node: Mapping) -> str:
        relation = {
            "包含任一": "包含任一",
            "包含全部": "包含全部",
            "全部不含": "全部不含",
            "为空": "为空",
            "数量至少": "至少",
        }.get(str(node.get("关系") or ""), str(node.get("关系") or ""))
        # 引擎的缺省：`对象` 省略按「事件」（`mechanics._condition_tags`）。
        raw = str(node.get("对象") or "")
        subject = {
            "事件": "本次事件", "来源": "来源", "目标": "目标", "状态": "状态", "技能": "技能",
        }.get(raw)
        if subject is None:
            subject = "本次事件" if not raw else self._fallback("标签条件对象不认识", "本次事件")
        labels = node.get("标签")
        rendered = _join([f"[{item}]" for item in labels]) if isinstance(labels, Sequence) else ""
        if relation in ("为空", "数量至少"):
            count = f"{_number(node.get('数量'))}个" if relation == "数量至少" else ""
            return f"{subject}的标签{relation}{count}"
        return f"{subject}的标签{relation}：{rendered}"

    def _condition_group(self, node: Mapping) -> str:
        raw = str(node.get("关系") or "")
        relation = {
            "全部成立": "且",
            "任一成立": "或",
            "全部不成立": "且都不成立",
        }.get(raw)
        if relation is None:
            # 引擎的缺省是「全部成立」，其余取值直接抛错——所以缺省照写，写了不认识的要报出来。
            relation = "且" if not raw else self._fallback("组合条件关系不认识", "且")
        return relation.join(self._condition(item) for item in node.get("条件") or ())

    # —— 数值 ——————————————————————————————————————————————

    def _ability_read_value(self, node: Mapping) -> str:
        source = str(node.get("来源") or "")
        owner = self._target(node.get("目标"))
        if source == "自身属性":
            base = f"自身{node.get('属性')}"
        elif source == "目标属性":
            base = f"{owner}的{node.get('属性')}"
        elif source == "构筑计量":
            base = f"[{node.get('计量')}]"
        elif source == "状态层数":
            base = f"[{node.get('状态')}]层数"
        elif source == "事件事实":
            base = f"本次事件的‹{node.get('事实')}›"
        elif source == "本次数值":
            base = "本次事件的数值"
        elif source == "战斗记录":
            base = f"{owner}记录的‹{node.get('名称')}›"
        elif source == "保存结果":
            base = f"‹{node.get('名称')}›"
        elif source == "自身当前血气":
            base = "自身当前血气"
        elif source == "自身当前精神":
            base = "自身当前精神"
        elif source == "自身当前护盾":
            base = "自身当前护盾"
        elif source == "目标当前血气":
            base = f"{owner}当前血气"
        elif source == "目标当前精神":
            base = f"{owner}当前精神"
        elif source == "目标当前护盾":
            base = f"{owner}当前护盾"
        elif source == "自身已损失血气":
            base = "自身已损失的血气"
        elif source == "自身已损失精神":
            base = "自身已损失的精神"
        elif source == "自身已损失护盾":
            base = "自身已损失的护盾"
        elif source == "目标已损失血气":
            base = f"{owner}已损失的血气"
        elif source == "目标已损失精神":
            base = f"{owner}已损失的精神"
        elif source == "目标已损失护盾":
            base = f"{owner}已损失的护盾"
        elif source == "行动条":
            # 引擎读的是 `行动进度 × 100`，所以正文也按百分数写。
            base = "自身行动条"
        elif source == "技能冷却":
            # 引擎读的是 `技能` 所选技能的冷却合计（见 `origin == "技能冷却"`）；
            # 该字段在数据里**可选**，省略时 `_select_skills` 返回全部技能，
            # 所以渲染也要认「没写技能」这一种（实测 30 条卡会因此抛 KeyError）。
            selector = node.get("技能")
            skills = (
                self._select_skill(selector)
                if _is_nodes(selector)
                else "全部技能"
            )
            base = f"{owner}的{skills}冷却"
        else:
            base = self._flag("读取数值.来源", source)
        if node.get("百分比") is not None:
            base = f"{base}×{_percent(node['百分比'])}"
        # 计量的上限已经写在「明细」里，读取点再标一次只会让条件句变吵。
        if source != "构筑计量":
            limits = []
            if node.get("最低值") is not None:
                limits.append(f"最低{_number(node['最低值'])}")
            if node.get("最高值") is not None:
                limits.append(f"最高{_number(node['最高值'])}")
            if limits:
                base += f"（{_join(limits)}）"
        return base

    def _ability_compute_value(self, node: Mapping) -> str:
        left = self._value(node.get("左值"))
        right = self._value(node.get("右值"))
        way = str(node.get("方式") or "")
        if way == "乘方":
            text = f"{left}的{right}次方"
        elif way in ("取小", "取大"):
            text = f"{left}与{right}取{'小' if way == '取小' else '大'}"
        elif way in ("相加", "相减", "相乘", "相除"):
            text = f"{left}{CALC_PHRASES[way]}{right}"
        else:
            text = f"{left}{way}{right}"
        limits = []
        if node.get("最低值") is not None:
            limits.append(f"最低{_number(node['最低值'])}")
        if node.get("最高值") is not None:
            limits.append(f"最高{_number(node['最高值'])}")
        return text + (f"（{_join(limits)}）" if limits else "")

    def _ability_random_value(self, node: Mapping) -> str:
        low, high = _number(node.get("最低值")), _number(node.get("最高值"))
        return f"{low}至{high}之间的随机值"

    def _ability_aggregate_value(self, node: Mapping) -> str:
        owner = self._target(node.get("目标"))
        way = {
            "数量": "数量",
            "总和": "总和",
            "最小": "最小值",
            "最大": "最大值",
            "平均": "平均值",
            "不同值数量": "不同值数量",
        }.get(str(node.get("方式") or ""), str(node.get("方式") or ""))
        hint = node.get("数值")
        if _is_nodes(hint):
            return f"{owner}的{way}（{self._effect(hint)}）"
        return f"{owner}的{way}"

    # —— 效果 ——————————————————————————————————————————————

    def _ability_deal_damage(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        value = self._value(node.get("数值"))
        form = node.get("伤害形式")
        kind = f"{form}伤害" if form and form != "普通" else "伤害"
        tail: list[str] = []
        if node.get("能否暴击"):
            tail.append("可暴击")
        if node.get("能否格挡"):
            tail.append("可格挡")
        if node.get("能否闪避") is False:
            tail.append("不可闪避")
        return f"对{target}造成{value}的{kind}" + (f"（{_join(tail)}）" if tail else "")

    def _ability_restore_resource(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        resource = RESOURCE_PHRASES.get(str(node.get("资源")), str(node.get("资源")))
        value = self._dedupe(target, self._value(node.get("数值")))
        return f"{target}恢复{value}点{resource}"

    def _ability_spend_resource(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        resource = RESOURCE_PHRASES.get(str(node.get("资源")), str(node.get("资源")))
        value = self._dedupe(target, self._value(node.get("数值")))
        text = f"{target}消耗{value}点{resource}"
        return text + self._short_fall(node)

    def _ability_set_resource(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        resource = RESOURCE_PHRASES.get(str(node.get("资源")), str(node.get("资源")))
        return f"将{target}的{resource}设为{self._value(node.get('数值'))}"

    def _ability_transfer_resource(self, node: Mapping) -> str:
        source = self._target(node.get("来源目标"))
        destination = self._target(node.get("接收目标"))
        return f"将{source}的{self._value(node.get('数值'))}点{node.get('来源资源')}转移给{destination}"

    def _ability_add_status(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        holder = node.get("状态") if isinstance(node.get("状态"), Mapping) else {}
        name = holder.get("名称")
        detail: list[str] = []
        if holder.get("持续单位"):
            detail.append(str(holder["持续单位"]))
        if holder.get("剩余行动") is not None:
            detail.append(f"持续{_number(holder['剩余行动'])}次行动")
        if holder.get("层数上限") is not None:
            detail.append(f"最多{_number(holder['层数上限'])}层")
        attributes = holder.get("属性")
        if isinstance(attributes, Mapping) and attributes:
            detail.append(_join([self._attribute_change(key, value) for key, value in attributes.items()]))
        return f"{target}获得[{name}]" + (f"（{_join(detail)}）" if detail else "")

    def _attribute_change(self, key: object, value: object) -> str:
        number = float(value)
        sign = "+" if number >= 0 else "−"
        return f"{key}{sign}{_number(abs(number))}"

    def _dedupe(self, target: str, value: str) -> str:
        """`自身恢复自身血气上限×24%` 里那个「自身」重复了，去掉一个。"""

        if target == "自身" and value.startswith("自身"):
            return value[len("自身"):]
        return value

    def _ability_remove_status(self, node: Mapping) -> str:
        return f"移除{self._select_status(node['状态'])}"

    def _ability_change_status_stacks(self, node: Mapping) -> str:
        """方向由 `方式` 决定。渲染措辞仍沿用「+N层」/「消耗N层」。

        曾经按能力名分成「增加状态层数」/「消耗状态层数」两个方法与两段正文，
        现在一个方法读 `方式`——措辞口径没变，只是判断来源统一了。

        **层数 ≥ 这个状态的层数上限时写「全部层数」**：数据里用 `101` / `1000` 这种
        「比上限还大」的数表示「有多少扣多少」，但正文写成「101层（不足则按实际值结算）」
        读起来像在精确扣 101 层。
        """

        state_ = self._select_status(node["状态"])
        if str(node.get("方式") or "增加") == "减少":
            if self._consumes_all(node):
                return f"消耗{state_}全部层数"
            return f"消耗{state_}{_number(node.get('层数'))}层" + self._short_fall(node)
        return f"{state_}+{_number(node.get('层数'))}层"

    def _consumes_all(self, node: Mapping) -> bool:
        """这一步是不是「有多少扣多少」。"""

        stacks = node.get("层数")
        if not isinstance(stacks, (int, float)) or isinstance(stacks, bool):
            return False
        choice = node.get("状态")
        label_ = choice.get("名称") if isinstance(choice, Mapping) else choice
        entry_ = self.statuses.get(str(label_) or "") or {}
        limit = entry_.get("层数上限")
        if not isinstance(limit, (int, float)) or isinstance(limit, bool):
            return False
        return float(stacks) >= float(limit)

    def _ability_change_status_duration(self, node: Mapping) -> str:
        """方向由 `方式` 决定：增加 → 延长，减少 → 缩短。"""

        state_ = self._select_status(node["状态"])
        action_ = "缩短" if str(node.get("方式") or "增加") == "减少" else "延长"
        return f"{state_}{action_}{_number(node.get('持续数值'))}次行动"

    def _ability_copy_status(self, node: Mapping) -> str:
        return f"将{self._select_status(node['状态'])}复制给{self._target(node.get('接收目标'))}"

    def _ability_transfer_status(self, node: Mapping) -> str:
        return f"将{self._select_status(node['状态'])}转移给{self._target(node.get('接收目标'))}"

    def _ability_change_action_gauge(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        value = self._value(node.get("数值"))
        way = str(node.get("方式") or "")
        if way == "增加":
            return f"{target}行动提前{value}点"
        if way == "减少":
            return f"{target}行动延后{value}点"
        return f"将{target}的行动条设为{value}"

    def _ability_change_skill_cooldown(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        skill = self._select_skill(node["技能"])
        value = node.get("数值")
        way = str(node.get("方式") or "")
        if way == "清空":
            return f"{target}的{skill}冷却清零"
        if way == "设置":
            return f"将{target}的{skill}冷却设为{self._value(value)}"
        verb = "增加" if way == "增加" else "减少"
        suffix = f"{self._value(value)}行动" if value is not None else "1次行动"
        return f"{target}的{skill}冷却{verb}{suffix}"

    def _ability_change_build_meter(self, node: Mapping) -> str:
        """计量的上限必须写在这一句里。

        原先上限只在「裁定」段的明细里出现，而裁定段只由**被动里读取本卡计量**的
        监听生成——于是「只在主动里读」的计量（实测 55 个，例如 `偷天蓄势`）
        上限从不出现在卡面上，玩家读到的 `[偷天蓄势]+13` 没有封顶信息。
        """

        name = node.get("计量")
        way = str(node.get("方式") or "")
        value = node.get("数值")
        if way == "清空":
            text = f"[{name}]清零"
        elif way == "设置":
            text = f"[{name}]设为{self._value(value)}"
        else:
            sign = "+" if way == "增加" else "−"
            text = f"[{name}]{sign}{self._value(value)}"
        if way != "清空" and node.get("最高值") is not None:
            text += f"（上限{_number(node['最高值'])}）"
        return text + self._short_fall(node)

    def _ability_extra_attack(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        return f"对{target}追加一次{_number(node.get('威力倍率'))}倍威力攻击"

    def _ability_share_damage(self, node: Mapping) -> str:
        return f"将{self._target(node.get('目标'))}受到的{_percent(node.get('比例'))}伤害分摊给其他己方"

    def _ability_transfer_damage(self, node: Mapping) -> str:
        return f"将{self._target(node.get('目标'))}受到的{self._value(node.get('数值'))}点伤害转移出去"

    def _ability_resist_lethal_damage(self, node: Mapping) -> str:
        keep = node.get("保留血气")
        suffix = f"，并至少保留{_number(keep)}点血气" if keep is not None else ""
        return f"抵挡一次致命伤害{suffix}"

    def _ability_revive(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        parts = []
        if node.get("血气百分比") is not None:
            parts.append(f"血气{_percent(node['血气百分比'])}")
        if node.get("精神百分比") is not None:
            parts.append(f"精神{_percent(node['精神百分比'])}")
        return f"复活{target}" + (f"（{_join(parts)}）" if parts else "")

    def _ability_modify_event_value(self, node: Mapping) -> str:
        way = {
            "增加": "增加",
            "减少": "减少",
            "设置": "设为",
            "乘算": "乘算",
        }.get(str(node.get("方式") or ""), str(node.get("方式") or ""))
        return f"本次事件的数值{way}{self._value(node.get('数值'))}"

    def _ability_modify_event_target(self, node: Mapping) -> str:
        return f"将本次事件的目标改为{self._target(node.get('目标'))}"

    def _ability_modify_event_tags(self, node: Mapping) -> str:
        way = {"添加": "添加", "移除": "移除", "设置": "设为"}.get(
            str(node.get("方式") or ""), str(node.get("方式") or "")
        )
        labels = node.get("标签")
        rendered = _join([f"[{item}]" for item in labels]) if isinstance(labels, Sequence) else ""
        return f"为本次事件{way}标签：{rendered}"

    def _ability_cancel_event(self, node: Mapping) -> str:
        return "无效本次事件"

    def _ability_pay_cost(self, node: Mapping) -> str:
        kind = str(node.get("代价类型") or "")
        amount = node.get("数值")
        if kind == "资源":
            text = f"支付{self._value(amount) if amount is not None else 1}点{node.get('资源')}"
        elif kind == "状态层数":
            status = self._select_status(node.get("状态"))
            text = f"消耗{status}{self._value(amount) if amount is not None else 1}层"
        elif kind == "行动条":
            text = f"行动延后{self._value(amount) if amount is not None else 1}点"
        elif kind == "技能冷却":
            skill = self._select_skill(node.get("技能"))
            text = f"{skill}冷却增加{self._value(amount) if amount is not None else 1}次行动"
        elif kind == "战斗对象":
            text = f"移除战斗对象{node.get('对象ID')}"
        else:
            text = self._flag("支付代价.代价类型", kind)
        return text + self._short_fall(node)

    def _ability_trigger_skill(self, node: Mapping) -> str:
        # 引擎的缺省：`目标` 省略 = 当前目标（`_select_targets`），所以走 `_target` 的缺省分支。
        target = self._target(node.get("目标"))
        skill = self._select_skill(node.get("技能"))
        marks = []
        if node.get("忽略代价"):
            marks.append("不消耗精神")
        if node.get("忽略冷却"):
            marks.append("无视冷却")
        return f"令{target}施展{skill}" + (f"（{_join(marks)}）" if marks else "")

    def _ability_record_combat_fact(self, node: Mapping) -> str:
        """「把当时的某个值记进一份历史」。

        原句式 `记录{owner}的‹史›为[值]（追加）（保留8条）` 读起来像
        「把值赋给史」，实际是**追加一条当时的快照**；两个括号挤在一起也分不清
        哪个是方式、哪个是保留上限。改成一句能读懂的：
        `将当时的[太乙归元]追加记入自身的‹逆生史›（只留最近8条）`。
        """

        # 引擎的缺省：`归属` 省略 = 效果来源自己（`_ability_record_fact` 取 `[source]`）；
        # `方式` 省略 = 追加。两者都照引擎写，不另立说法。
        owner = self._target(node.get("归属")) if node.get("归属") else "自身"
        way = {"追加": "追加记入", "覆盖": "覆盖为", "累加": "累加", "清空": "清空"}.get(
            str(node.get("方式") or "追加"), "记入"
        )
        value = node.get("值")
        # 「当时的」只对**读取出来的量**成立（读计量/读血气…）；值是常量时不能这么说
        # （实测战丹写成「将当时的1累加进…」不通）。
        is_read = isinstance(value, Mapping) and value.get("能力") == "读取数值"
        if value is None:
            text = f"{way}{owner}的‹{node.get('名称')}›"
        elif is_read:
            text = f"将当时的{self._value(value)}{way}{owner}的‹{node.get('名称')}›"
        else:
            # 「累加」要带「进」，否则「把1累加自身的‹X›」不成句。
            link = "进" if way == "累加" else ""
            text = f"把{self._value(value)}{way}{link}{owner}的‹{node.get('名称')}›"
        if node.get("保留数量") is not None:
            text += f"（只留最近{_number(node['保留数量'])}条）"
        return text

    def _ability_modify_battle_relation(self, node: Mapping) -> str:
        # 引擎的缺省：`方式` 省略 = 建立（`_ability_modify_relation`），不是解除。
        way = "解除" if str(node.get("方式") or "建立") == "解除" else "建立"
        left = self._target(node.get("一方"))
        right = self._target(node.get("另一方"))
        return f"在{left}与{right}之间{way}关联‹{node.get('名称')}›"

    def _ability_modify_skill(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        skill = self._select_skill(node["技能"])
        way = {"设置": "设为", "增加": "增加", "减少": "减少", "追加": "追加"}.get(
            str(node.get("方式") or ""), "设为"
        )
        return f"将{target}的{skill}的{node.get('字段')}{way}{self._value(node.get('值'))}"

    def _ability_copy_skill(self, node: Mapping) -> str:
        source = self._target(node.get("来源目标"))
        destination = self._target(node.get("接收目标"))
        return f"将{source}的{self._select_skill(node['技能'])}复制给{destination}"

    def _ability_modify_action_intent(self, node: Mapping) -> str:
        """改的是**行动者那次行动**的意图，不是「〈目标〉的意图」。

        `目标` 字段是「意图被改成的**新目标**」，不是意图的归属者。原先写成
        `f"{target}的行动意图{field}"`，于是 `{字段: 取消}` 渲染成
        「自身的行动意图取消本次行动」——而它取消的是**对手**的行动，
        玩家读到的意思正好相反。所以主体一律用中性且准确的「该次行动」。
        """

        field = str(node.get("字段") or "")
        if field == "取消":
            return "取消该次行动"
        if field == "行动":
            return f"将该次行动改为{node.get('值') or '指定行动'}"
        if field == "目标":
            if not node.get("目标"):
                return "将该次行动的目标改为本次事件的目标"
            return f"将该次行动的目标改为{self._target(node.get('目标'))}"
        if field == "技能":
            return f"将该次行动的技能改为{self._select_skill(node['技能'])}"
        return f"将该次行动的{field}改写"

    def _ability_convert_event(self, node: Mapping) -> str:
        return f"将本次事件转化为{node.get('事件')}"

    def _ability_modify_check(self, node: Mapping) -> str:
        way = {
            "必定成功": "必定成功",
            "必定失败": "必定失败",
            "反转": "结果反转",
            "重掷取优": "重掷取优",
        }.get(str(node.get("方式") or ""), str(node.get("方式") or ""))
        text = f"本次{node.get('判定')}判定{way}"
        if node.get("次数") is not None:
            text += f"（{_number(node['次数'])}次）"
        return text

    def _ability_modify_battle_rule(self, node: Mapping) -> str:
        name = node.get("名称")
        if node.get("方式") == "移除":
            return f"移除战场规则‹{name}›"
        body = node.get("规则")
        inner = ""
        if isinstance(body, Mapping):
            listeners = body.get("监听")
            if isinstance(listeners, Sequence) and not isinstance(listeners, (str, bytes)):
                clauses = [
                    self._effects(item.get("效果"))
                    for item in listeners
                    if isinstance(item, Mapping)
                ]
                if clauses:
                    inner = "（" + "；".join(clauses) + "）"
        if node.get("来源退场时移除"):
            self._defer("来源退场时移除")
        return f"添加战场规则‹{name}›" + (f"：{inner}" if inner else "")

    def _ability_save_result(self, node: Mapping) -> str:
        """把某一步的结果存下来给后面用。

        原句 `记为‹逆生果›` 没说值从哪来——读的人得自己猜。实际上 `来源`
        只有两种：`上个效果`（141 处）与 `指定值`（13 处）。
        """

        if str(node.get("来源") or "") == "指定值":
            return f"把{self._value(node.get('值'))}存为‹{node.get('名称')}›"
        return f"把上一步的结果存为‹{node.get('名称')}›"

    def _ability_switch_form(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        definition = node.get("定义")
        detail = ""
        if isinstance(definition, Mapping):
            attributes = definition.get("属性变化")
            if isinstance(attributes, Mapping) and attributes:
                detail = _join([self._attribute_change(key, value) for key, value in attributes.items()])
        return f"{target}进入[{node.get('形态')}]" + (f"（{detail}）" if detail else "")

    def _ability_create_object(self, node: Mapping) -> str:
        definition = node.get("定义") if isinstance(node.get("定义"), Mapping) else {}
        name = definition.get("名称") or "构造物"
        marks = []
        attributes = definition.get("属性")
        if isinstance(attributes, Mapping) and attributes:
            marks.append(_join([self._attribute_change(key, value) for key, value in attributes.items()]))
        if node.get("阵营"):
            marks.append(f"阵营：{node['阵营']}")
        # 引擎的缺省：参战者的 `身份` 省略 = 召唤物（`_ability_create_object` 取
        # `definition.get("身份") or "召唤物"`），不是「参战者」。
        kind = str(definition.get("身份") or ("构造物" if node.get("类型") == "构造物" else "召唤物"))
        return f"召出{kind}[{name}]" + (f"（{_join(marks)}）" if marks else "")

    def _ability_remove_object(self, node: Mapping) -> str:
        """`对象ID` 在登记表里**允许空**（默认空串）。

        引擎对空值的语义是「移除来源自己拥有的全部召唤物与构造物」
        （见 `mechanics._ability_remove_object` 的 `not object_id and owner_id == source.id`）。
        原先直接拼 `node.get('对象ID')`，缺省时把 Python 的 `None` 打进了卡面
        （实测 22 处）。
        """

        object_id = str(node.get("对象ID") or "").strip()
        if not object_id:
            return "移除自身拥有的全部战斗对象"
        return f"移除战斗对象‹{object_id}›"

    # 注：读取「施法者自己」的 7 个来源（自身当前X / 自身已损失的X / 自身行动条）
    # 在正文里仍写「自身」。**不要**统一改成「施法者」：那会让 44% 的实体正文变样，
    # 而其中绝大多数是「自身恢复…」这种主语已经写明施法者的句子，加完更拗口
    # （`自身恢复施法者已损失的精神`）。真正的歧义只在「遍历下面读施法者属性」那一
    # 小撮，而那里「自身」紧跟在目标之后、有上下文可循。

    def _ability_change_owner(self, node: Mapping) -> str:
        """名字与后缀不能硬拼。

        原句 `将敌方的阵营改为{阵营}方` 遇上以「方」收尾的名字会叠成
        「改为己方方」（实测 1 处）。把名字放进 `‹›`、阵营二字明写，就不会粘。
        """

        target = self._target(node.get("目标"))
        field = {"阵营": "阵营", "主人": "主人", "控制者": "控制者"}.get(
            str(node.get("字段") or ""), str(node.get("字段") or "")
        )
        if node.get("归属目标"):
            return f"将{target}的{field}改到{self._target(node['归属目标'])}"
        return f"将{target}的{field}改到‹{node.get('阵营')}›"

    def _ability_replay_effect(self, node: Mapping) -> str:
        # 引擎的缺省：`范围` 省略 = 上个效果（`_ability_replay_effect`）。
        scope = "上一项效果" if str(node.get("范围") or "上个效果") == "上个效果" else "自身上一项效果"
        target = f"，目标改为{self._target(node['目标'])}" if node.get("目标") else ""
        ratio = f"（{_number(node.get('倍率'))}倍）" if node.get("倍率") is not None else ""
        return f"重复{scope}{target}{ratio}"

    def _ability_modify_tactic(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        way = {"替换": "替换为", "追加": "追加", "清空": "清空"}.get(
            str(node.get("方式") or ""), "替换为"
        )
        if way == "清空":
            return f"清空{target}的战术"
        return f"将{target}的战术{way}{self._tactics(node.get('战术'))}"

    def _tactics(self, value: object) -> str:
        """把战术表写成中文，而不是把 Python 结构倒给玩家。

        原先这里是 `f"[{node.get('战术')}]"`，于是正文里出现
        `[({'行动': '技能', '目标排序': '随机'},)]`——元组、`MappingProxy` 这些
        **内部表现的 `repr`** 直接进了卡面。同一个战术表在不同读取路径下包装不同
        （一次是 `MappingProxy`，一次是展开深拷贝后的普通字典），正文就跟着变。
        """

        if value is None:
            return ""
        items = value if isinstance(value, (list, tuple)) else [value]
        return "[" + "、".join(self._tactic(item) for item in items) + "]"

    def _tactic(self, item: object) -> str:
        if isinstance(item, Mapping):
            action = str(item.get("行动") or "")
            order = item.get("目标排序")
            text = action or "—"
            if order:
                text += f"（目标排序：{order}）"
            return text
        return str(item)

    def _ability_fixed_attribute_bonus(self, node: Mapping) -> str:
        attributes = node.get("属性")
        if not isinstance(attributes, Mapping):
            return self._flag("固定属性加成", "缺少属性")
        return "永久获得：" + _join(
            [self._attribute_change(key, value) for key, value in attributes.items()]
        )

    # —— 组合能力 ——————————————————————————————————————————————

    def _ability_sequence(self, node: Mapping) -> str:
        return self._effects(node.get("效果"))

    def _ability_conditional(self, node: Mapping) -> str:
        text = f"若{self._conditions(node.get('条件'))}，则{self._block(node.get('成立效果'))}"
        if node.get("不成立效果"):
            text += f"；否则{self._block(node['不成立效果'])}"
        return text

    def _ability_random_branch(self, node: Mapping) -> str:
        options = node.get("选项") or ()
        drawn = node.get("抽取数量")
        head = f"随机执行{drawn}项" if drawn else "随机执行1项"
        if node.get("是否放回"):
            head += "（抽取后放回）"
        body = " / ".join(self._effect(item) for item in options)
        return f"{head}（{body}）"

    def _ability_iterate_targets(self, node: Mapping) -> str:
        return f"对{self._target(node.get('目标'))}逐个执行：{self._block(node.get('效果'))}"

    def _ability_repeat(self, node: Mapping) -> str:
        times = self._value(node.get("次数"))
        head = f"至多重复{times}次" if node.get("失败时停止") else f"重复{times}次"
        return f"{head}：{self._block(node.get('效果'))}"

    def _ability_attempt(self, node: Mapping) -> str:
        trial = self._block(node.get("尝试效果"))
        success = node.get("成功效果")
        failure = node.get("失败效果")
        # 成功与失败分支同内容是引擎里**唯一**能表达「尝试之后无论如何都做某件事」的
        # 写法：`_run_effects` 短路返回，把它写进同一个效果数组，尝试失败时就会被跳过。
        # 文本上收成一句，别让玩家读到两个一模一样的句子。
        if failure is not None and _fingerprint(success) == _fingerprint(failure):
            return f"{trial}；然后无论成败，{self._block(success)}"
        text = f"{trial}；若能则{self._block(success)}"
        if failure is not None:
            text += f"；若不能则{self._block(failure)}"
        return text

    def _ability_transaction(self, node: Mapping) -> str:
        text = f"一并{self._block(node.get('效果'))}"
        if node.get("失败效果"):
            text += f"；若不成立则{self._block(node['失败效果'])}"
        return text

    def _ability_listen_event(self, node: Mapping) -> str:
        """被动槽位里的监听应当由 `_passive` 处理；走到这里说明嵌套位置不对。"""

        return self._flag("监听事件", "出现在非被动槽位")

    # —— 公共片段 ——————————————————————————————————————————————

    def _short_fall(self, node: Mapping) -> str:
        if node.get("不足时是否失败") is True:
            return "（不足则本次不结算）"
        if node.get("不足时是否失败") is False:
            return "（不足则按实际值结算）"
        return ""


def render_body(entity: Mapping[str, object]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """渲染一份实体的规则正文，返回 (行, 未支持项)。"""

    renderer = CardText(entity)
    return renderer.body(), tuple(renderer.unknown)


def render_listeners(
    holder: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """只渲染一块状态承载的监听节点。

    长期伤势的 `战斗状态` 就是这样：`类别 / 剩余行动 / 属性` 由展示层的结构化行负责，
    真正带时序规则的是 `监听`，按同一套条件/处理/明细措辞写出来。
    """

    renderer = CardText(holder)
    lines: list[str] = []
    for node in holder.get("监听") or ():
        if isinstance(node, Mapping) and node.get("能力") == "监听事件":
            lines.extend(renderer._listener(node))
        else:
            ability = node.get("能力") if isinstance(node, Mapping) else node
            lines.append(renderer._flag("监听", str(ability)))
    return tuple(lines), tuple(renderer.unknown)


__all__ = ["CardText", "render_body", "render_listeners"]
