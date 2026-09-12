"""把构筑的能力树渲染成玩家读的规则正文。

`说明` 里从「主动」开始的正文由本模块生成，卡头那行风味简介仍由人写。
渲染规则见 `data/战斗/内容/文本规范.md`；本模块是那份规范的唯一实现。

三条硬要求：

* **不猜**。只写引擎已经能表达的东西。节点里没有的语义一律不补。
* **不漏**。任何一个原子能力、任何一个事件都必须有措辞；认不出来就记进
  `unknown` 并在正文里留下 `〈未支持：X〉`，由 `tools/架构审查/检查战斗文本.py` 报错。
* **不改数据**。渲染是只读的，拿同一棵树渲染两次必须完全一样。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

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
            lines.append("被动：")
            for index, skill in enumerate(passives, 1):
                lines.extend(self._passive(index, skill))
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
        name = self._short_name(skill.get("名称"))
        title = [f"耗神{_number(skill['精神消耗'])}"] if "精神消耗" in skill else []
        if "冷却行动" in skill:
            title.append(f"冷却{_number(skill['冷却行动'])}行动")
        lines = [
            f"{_ordinal(index)}[{name}]　主动" + (" · " + " · ".join(title) if title else "")
        ]
        condition = []
        attempt = skill.get("使用次数")
        if attempt is not None:
            condition.append(f"整场最多施展{_number(attempt)}次")
        if condition:
            lines.append("条件：" + "；".join(condition) + "。")
        trigger = self._activation(skill)
        if trigger:
            lines.append("发动：" + trigger + "。")
        lines.append("处理：" + self._effects(skill.get("效果")) + "。")
        detail = self._drain() + self._skill_detail(skill)
        if detail:
            lines.append("明细：" + " · ".join(detail))
        return lines

    def _short_name(self, value: object) -> str:
        """技能名在 JSON 里是 `卡名·短名`，文本里只写短名。"""

        text = str(value or "未命名")
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
        labels = skill.get("标签")
        if isinstance(labels, Sequence) and not isinstance(labels, (str, bytes)) and labels:
            detail.append("标签：" + _join([str(item) for item in labels]))
        return detail

    def _passive(self, index: int, skill: Mapping) -> list[str]:
        name = self._short_name(skill.get("名称"))
        lines = [f"{_ordinal(index)}[{name}]　被动"]
        for node in skill.get("效果") or ():
            if not isinstance(node, Mapping) or node.get("能力") != "监听事件":
                self._flag("被动技能.效果", str(node.get("能力") if isinstance(node, Mapping) else node))
                continue
            # 读本卡计量的监听属于结算段，单独放进「裁定」，不在被动里重复一遍。
            if self._read_counters(node):
                continue
            lines.extend(self._listener(node))
        return lines

    def _listener(self, node: Mapping) -> list[str]:
        lines = ["条件：" + self._trigger(node) + "。"]
        lines.append("处理：" + self._effects(node.get("效果")) + "。")
        detail = self._drain() + self._listener_detail(node)
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

    def _listener_detail(self, node: Mapping) -> list[str]:
        detail: list[str] = []
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
        """计量结算段：被动里读取本卡计量的监听节点。"""

        lines: list[str] = []
        if not self.counters:
            return lines
        seen: set[str] = set()
        index = 1
        for skill in passives:
            for node in skill.get("效果") or ():
                if not isinstance(node, Mapping) or node.get("能力") != "监听事件":
                    continue
                names = self._read_counters(node)
                if not names:
                    continue
                key = f"{skill.get('名称')}:{node.get('事件')}:{','.join(sorted(names))}"
                if key in seen:
                    continue
                seen.add(key)
                lines.append(f"{_ordinal(index)}[{_join(sorted(names))}]　计量")
                lines.append("条件：" + self._trigger(node) + "。")
                lines.append("处理：" + self._effects(node.get("效果")) + "。")
                detail = self._drain() + self._listener_detail(node)
                detail.extend(self._counter_limits(sorted(names)))
                if detail:
                    lines.append("明细：" + " · ".join(detail))
                index += 1
        return lines

    def _read_counters(self, node: object) -> set[str]:
        names: set[str] = set()
        for child in self._walk(node):
            if child.get("能力") == "读取数值" and child.get("来源") == "构筑计量":
                name = child.get("计量")
                if isinstance(name, str) and name in self.counters:
                    names.add(name)
        return names

    def _counter_limits(self, names: Sequence[str]) -> list[str]:
        detail: list[str] = []
        for name in names:
            node = self.counters[name]
            if node.get("最高值") is not None:
                detail.append(f"[{name}]上限{_number(node['最高值'])}")
            if node.get("最低值") is not None:
                detail.append(f"[{name}]最低{_number(node['最低值'])}")
        return detail

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

    def _effect(self, node: object) -> str:
        if not isinstance(node, Mapping):
            return self._flag("效果", str(node))
        ability = str(node.get("能力") or "")
        handler = getattr(self, f"_ability_{ability}", None)
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
        handler = getattr(self, f"_condition_{ability}", None)
        if handler is None:
            return self._flag("条件能力", ability)
        return handler(node)

    def _value(self, node: object) -> str:
        """数值位置：能力节点走渲染，裸值直接写。"""

        if _is_nodes(node):
            return self._effect(node)
        if isinstance(node, (int, float)) and not isinstance(node, bool):
            return _number(node)
        return str(node)

    # —— 目标 ——————————————————————————————————————————————

    def _target(self, node: object) -> str:
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

    def _select_skill(self, node: Mapping) -> str:
        raw = str(node.get("范围") or "")
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

    def _select_status(self, node: Mapping) -> str:
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

    def _condition_概率条件(self, node: Mapping) -> str:
        return f"有{self._value(node.get('概率'))}%概率"

    def _condition_数值条件(self, node: Mapping) -> str:
        left = self._value(node.get("左值"))
        right = self._value(node.get("右值"))
        compare = COMPARE_PHRASES.get(str(node.get("比较") or ""), str(node.get("比较") or ""))
        return f"{left}{compare}{right}"

    def _condition_状态条件(self, node: Mapping) -> str:
        owner = self._target(node.get("目标"))
        compare = COMPARE_PHRASES.get(str(node.get("比较") or ""), str(node.get("比较") or ""))
        stacks = node.get("层数")
        prefix = f"{owner}的[{node.get('状态')}]"
        return f"{prefix}层数{compare}{_number(stacks)}" if compare else prefix

    def _condition_类型条件(self, node: Mapping) -> str:
        side = {"来源": "来源", "目标": "目标"}.get(str(node.get("对象") or ""), "目标")
        return f"{side}是{node.get('值')}"

    def _condition_标签条件(self, node: Mapping) -> str:
        relation = {
            "包含任一": "包含任一",
            "包含全部": "包含全部",
            "全部不含": "全部不含",
            "为空": "为空",
            "数量至少": "至少",
        }.get(str(node.get("关系") or ""), str(node.get("关系") or ""))
        subject = {"事件": "本次事件", "来源": "来源", "目标": "目标", "状态": "状态", "技能": "技能"}.get(
            str(node.get("对象") or ""), "本次事件"
        )
        labels = node.get("标签")
        rendered = _join([f"[{item}]" for item in labels]) if isinstance(labels, Sequence) else ""
        if relation in ("为空", "数量至少"):
            count = f"{_number(node.get('数量'))}个" if relation == "数量至少" else ""
            return f"{subject}的标签{relation}{count}"
        return f"{subject}的标签{relation}：{rendered}"

    def _condition_组合条件(self, node: Mapping) -> str:
        relation = {
            "全部成立": "且",
            "任一成立": "或",
            "全部不成立": "且都不成立",
        }.get(str(node.get("关系") or ""), "且")
        return relation.join(self._condition(item) for item in node.get("条件") or ())


    # —— 数值 ——————————————————————————————————————————————

    def _ability_读取数值(self, node: Mapping) -> str:
        source = str(node.get("来源") or "")
        owner = self._target(node["目标"]) if _is_nodes(node.get("目标")) else "目标"
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
        elif source == "自身已损失血气":
            base = "自身已损失的血气"
        elif source == "目标当前血气":
            base = f"{owner}当前血气"
        elif source == "目标当前精神":
            base = f"{owner}当前精神"
        elif source == "目标已损失血气":
            base = f"{owner}已损失的血气"
        elif source == "目标已损失精神":
            base = f"{owner}已损失的精神"
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

    def _ability_计算数值(self, node: Mapping) -> str:
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

    def _ability_随机数值(self, node: Mapping) -> str:
        low, high = _number(node.get("最低值")), _number(node.get("最高值"))
        return f"{low}至{high}之间的随机值"

    def _ability_聚合数值(self, node: Mapping) -> str:
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

    def _ability_造成伤害(self, node: Mapping) -> str:
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

    def _ability_恢复资源(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        resource = RESOURCE_PHRASES.get(str(node.get("资源")), str(node.get("资源")))
        value = self._dedupe(target, self._value(node.get("数值")))
        return f"{target}恢复{value}点{resource}"

    def _ability_消耗资源(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        resource = RESOURCE_PHRASES.get(str(node.get("资源")), str(node.get("资源")))
        value = self._dedupe(target, self._value(node.get("数值")))
        text = f"{target}消耗{value}点{resource}"
        return text + self._short_fall(node)

    def _ability_设置资源(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        resource = RESOURCE_PHRASES.get(str(node.get("资源")), str(node.get("资源")))
        return f"将{target}的{resource}设为{self._value(node.get('数值'))}"

    def _ability_转移资源(self, node: Mapping) -> str:
        source = self._target(node.get("来源目标"))
        destination = self._target(node.get("接收目标"))
        return f"将{source}的{self._value(node.get('数值'))}点{node.get('来源资源')}转移给{destination}"

    def _ability_添加状态(self, node: Mapping) -> str:
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

    def _ability_移除状态(self, node: Mapping) -> str:
        return f"移除{self._select_status(node['状态'])}"

    def _ability_增加状态层数(self, node: Mapping) -> str:
        return f"{self._select_status(node['状态'])}+{_number(node.get('层数'))}层"

    def _ability_消耗状态层数(self, node: Mapping) -> str:
        text = f"消耗{self._select_status(node['状态'])}{_number(node.get('层数'))}层"
        return text + self._short_fall(node)

    def _ability_延长状态(self, node: Mapping) -> str:
        return f"{self._select_status(node['状态'])}延长{_number(node.get('持续数值'))}次行动"

    def _ability_缩短状态(self, node: Mapping) -> str:
        return f"{self._select_status(node['状态'])}缩短{_number(node.get('持续数值'))}次行动"

    def _ability_复制状态(self, node: Mapping) -> str:
        return f"将{self._select_status(node['状态'])}复制给{self._target(node.get('接收目标'))}"

    def _ability_转移状态(self, node: Mapping) -> str:
        return f"将{self._select_status(node['状态'])}转移给{self._target(node.get('接收目标'))}"

    def _ability_修改行动条(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        value = self._value(node.get("数值"))
        way = str(node.get("方式") or "")
        if way == "增加":
            return f"{target}行动提前{value}点"
        if way == "减少":
            return f"{target}行动延后{value}点"
        return f"将{target}的行动条设为{value}"

    def _ability_修改技能冷却(self, node: Mapping) -> str:
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

    def _ability_修改构筑计量(self, node: Mapping) -> str:
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
        return text + self._short_fall(node)

    def _ability_追加攻击(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        return f"对{target}追加一次{_number(node.get('威力倍率'))}倍威力攻击"

    def _ability_分摊伤害(self, node: Mapping) -> str:
        return f"将{self._target(node.get('目标'))}受到的{_percent(node.get('比例'))}伤害分摊给其他己方"

    def _ability_转移伤害(self, node: Mapping) -> str:
        return f"将{self._target(node.get('目标'))}受到的{self._value(node.get('数值'))}点伤害转移出去"

    def _ability_抵挡致命伤害(self, node: Mapping) -> str:
        keep = node.get("保留血气")
        suffix = f"，并至少保留{_number(keep)}点血气" if keep is not None else ""
        return f"抵挡一次致命伤害{suffix}"

    def _ability_复活(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        parts = []
        if node.get("血气百分比") is not None:
            parts.append(f"血气{_percent(node['血气百分比'])}")
        if node.get("精神百分比") is not None:
            parts.append(f"精神{_percent(node['精神百分比'])}")
        return f"复活{target}" + (f"（{_join(parts)}）" if parts else "")

    def _ability_修改事件数值(self, node: Mapping) -> str:
        way = {
            "增加": "增加",
            "减少": "减少",
            "设置": "设为",
            "乘算": "乘算",
        }.get(str(node.get("方式") or ""), str(node.get("方式") or ""))
        return f"本次事件的数值{way}{self._value(node.get('数值'))}"

    def _ability_修改事件目标(self, node: Mapping) -> str:
        return f"将本次事件的目标改为{self._target(node.get('目标'))}"

    def _ability_修改事件标签(self, node: Mapping) -> str:
        way = {"添加": "添加", "移除": "移除", "设置": "设为"}.get(
            str(node.get("方式") or ""), str(node.get("方式") or "")
        )
        labels = node.get("标签")
        rendered = _join([f"[{item}]" for item in labels]) if isinstance(labels, Sequence) else ""
        return f"为本次事件{way}标签：{rendered}"

    def _ability_取消事件(self, node: Mapping) -> str:
        return "无效本次事件"

    def _ability_支付代价(self, node: Mapping) -> str:
        kind = str(node.get("代价类型") or "")
        amount = node.get("数值")
        if kind == "资源":
            text = f"支付{self._value(amount) if amount is not None else 1}点{node.get('资源')}"
        elif kind == "状态层数":
            status = self._select_status(node["状态"]) if _is_nodes(node.get("状态")) else "状态"
            text = f"消耗{status}{self._value(amount) if amount is not None else 1}层"
        elif kind == "行动条":
            text = f"行动延后{self._value(amount) if amount is not None else 1}点"
        elif kind == "技能冷却":
            skill = self._select_skill(node["技能"]) if _is_nodes(node.get("技能")) else "技能"
            text = f"{skill}冷却增加{self._value(amount) if amount is not None else 1}次行动"
        elif kind == "战斗对象":
            text = f"移除战斗对象{node.get('对象ID')}"
        else:
            text = self._flag("支付代价.代价类型", kind)
        return text + self._short_fall(node)

    def _ability_触发技能(self, node: Mapping) -> str:
        target = self._target(node.get("目标")) if node.get("目标") else "自身"
        skill = self._select_skill(node["技能"])
        marks = []
        if node.get("忽略代价"):
            marks.append("不消耗精神")
        if node.get("忽略冷却"):
            marks.append("无视冷却")
        return f"令{target}施展{skill}" + (f"（{_join(marks)}）" if marks else "")

    def _ability_记录战斗事实(self, node: Mapping) -> str:
        owner = self._target(node.get("归属")) if node.get("归属") else "自身"
        way = {"追加": "追加", "覆盖": "覆盖", "累加": "累加", "清空": "清空"}.get(
            str(node.get("方式") or ""), ""
        )
        text = f"记录{owner}的‹{node.get('名称')}›"
        text += f"为{self._value(node.get('值'))}" if node.get("值") is not None else ""
        if way:
            text += f"（{way}）"
        if node.get("保留数量") is not None:
            text += f"（保留{_number(node['保留数量'])}条）"
        return text

    def _ability_修改战斗关联(self, node: Mapping) -> str:
        way = "建立" if node.get("方式") == "建立" else "解除"
        left = self._target(node.get("一方"))
        right = self._target(node.get("另一方"))
        return f"在{left}与{right}之间{way}关联‹{node.get('名称')}›"

    def _ability_修改技能(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        skill = self._select_skill(node["技能"])
        way = {"设置": "设为", "增加": "增加", "减少": "减少", "追加": "追加"}.get(
            str(node.get("方式") or ""), "设为"
        )
        return f"将{target}的{skill}的{node.get('字段')}{way}{self._value(node.get('值'))}"

    def _ability_复制技能(self, node: Mapping) -> str:
        source = self._target(node.get("来源目标"))
        destination = self._target(node.get("接收目标"))
        return f"将{source}的{self._select_skill(node['技能'])}复制给{destination}"

    def _ability_修改行动意图(self, node: Mapping) -> str:
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

    def _ability_转化事件(self, node: Mapping) -> str:
        return f"将本次事件转化为{node.get('事件')}"

    def _ability_修改判定(self, node: Mapping) -> str:
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

    def _ability_修改战场规则(self, node: Mapping) -> str:
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

    def _ability_保存结果(self, node: Mapping) -> str:
        if node.get("来源") == "指定值":
            return f"记为{self._value(node.get('值'))}"
        return f"记为‹{node.get('名称')}›"

    def _ability_切换形态(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        definition = node.get("定义")
        detail = ""
        if isinstance(definition, Mapping):
            attributes = definition.get("属性变化")
            if isinstance(attributes, Mapping) and attributes:
                detail = _join([self._attribute_change(key, value) for key, value in attributes.items()])
        return f"{target}进入[{node.get('形态')}]" + (f"（{detail}）" if detail else "")

    def _ability_创建战斗对象(self, node: Mapping) -> str:
        definition = node.get("定义") if isinstance(node.get("定义"), Mapping) else {}
        name = definition.get("名称") or "构造物"
        marks = []
        attributes = definition.get("属性")
        if isinstance(attributes, Mapping) and attributes:
            marks.append(_join([self._attribute_change(key, value) for key, value in attributes.items()]))
        if node.get("阵营"):
            marks.append(f"阵营：{node['阵营']}")
        kind = str(definition.get("身份") or ("构造物" if node.get("类型") == "构造物" else "参战者"))
        return f"召出{kind}[{name}]" + (f"（{_join(marks)}）" if marks else "")

    def _ability_移除战斗对象(self, node: Mapping) -> str:
        return f"移除战斗对象{node.get('对象ID')}"

    def _ability_修改归属(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        field = {"阵营": "阵营", "主人": "主人", "控制者": "控制者"}.get(
            str(node.get("字段") or ""), str(node.get("字段") or "")
        )
        if node.get("归属目标"):
            return f"将{target}的{field}改为{self._target(node['归属目标'])}"
        return f"将{target}的{field}改为{node.get('阵营')}方"

    def _ability_回放效果(self, node: Mapping) -> str:
        scope = "上一项效果" if node.get("范围") == "上个效果" else "自身上一项效果"
        target = f"，目标改为{self._target(node['目标'])}" if node.get("目标") else ""
        ratio = f"（{_number(node.get('倍率'))}倍）" if node.get("倍率") is not None else ""
        return f"重复{scope}{target}{ratio}"

    def _ability_修改战术(self, node: Mapping) -> str:
        target = self._target(node.get("目标"))
        way = {"替换": "替换为", "追加": "追加", "清空": "清空"}.get(
            str(node.get("方式") or ""), "替换为"
        )
        if way == "清空":
            return f"清空{target}的战术"
        return f"将{target}的战术{way}[{node.get('战术')}]"

    def _ability_固定属性加成(self, node: Mapping) -> str:
        attributes = node.get("属性")
        if not isinstance(attributes, Mapping):
            return self._flag("固定属性加成", "缺少属性")
        return "永久获得：" + _join(
            [self._attribute_change(key, value) for key, value in attributes.items()]
        )

    # —— 组合能力 ——————————————————————————————————————————————

    def _ability_顺序执行(self, node: Mapping) -> str:
        return self._effects(node.get("效果"))

    def _ability_条件执行(self, node: Mapping) -> str:
        text = f"若{self._conditions(node.get('条件'))}，则{self._block(node.get('成立效果'))}"
        if node.get("不成立效果"):
            text += f"；否则{self._block(node['不成立效果'])}"
        return text

    def _ability_随机执行(self, node: Mapping) -> str:
        options = node.get("选项") or ()
        drawn = node.get("抽取数量")
        head = f"随机执行{drawn}项" if drawn else "随机执行1项"
        if node.get("是否放回"):
            head += "（抽取后放回）"
        body = " / ".join(self._effect(item) for item in options)
        return f"{head}（{body}）"

    def _ability_遍历目标(self, node: Mapping) -> str:
        return f"对{self._target(node.get('目标'))}逐个执行：{self._block(node.get('效果'))}"

    def _ability_重复执行(self, node: Mapping) -> str:
        times = self._value(node.get("次数"))
        head = f"至多重复{times}次" if node.get("失败时停止") else f"重复{times}次"
        return f"{head}：{self._block(node.get('效果'))}"

    def _ability_尝试执行(self, node: Mapping) -> str:
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

    def _ability_事务执行(self, node: Mapping) -> str:
        text = f"一并{self._block(node.get('效果'))}"
        if node.get("失败效果"):
            text += f"；若不成立则{self._block(node['失败效果'])}"
        return text

    def _ability_监听事件(self, node: Mapping) -> str:
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
