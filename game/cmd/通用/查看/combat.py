"""战斗能力、技能、状态与条件渲染。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re

from message import M

from .utils import (
    _display_name,
    _display_number,
    _signed,
)


def _combat_lines(
    node: Mapping[str, object], related: Mapping[str, object] | None = None
) -> tuple[str, ...]:
    related = related or {}
    ability = str(node.get("能力") or "")
    if ability == "顺序执行":
        effects = node.get("效果")
        if isinstance(effects, Sequence) and not isinstance(effects, (str, bytes)):
            lines = tuple(
                line
                for effect in effects
                if isinstance(effect, Mapping)
                for line in _combat_lines(effect, related)
            )
            if len(lines) > 1:
                return ("依次处理：" + "；".join(lines),)
            return lines
        return ()
    if ability == "条件执行":
        condition = _conditions(node.get("条件"))
        success = "；".join(_nodes(node.get("成立效果"), related)) or "不产生额外效果"
        failure = "；".join(_nodes(node.get("不成立效果"), related))
        suffix = f"；否则：{failure}" if failure else ""
        return (f"若{condition}：{success}{suffix}",)
    if ability == "随机执行":
        options = node.get("选项")
        summaries = []
        if isinstance(options, Sequence) and not isinstance(options, (str, bytes)):
            for option in options:
                if isinstance(option, Mapping):
                    summaries.extend(_combat_lines(option, related)[:1])
        count = node.get("抽取数量", 1)
        replacement = "，可重复抽取" if node.get("是否放回") else ""
        draw = "随机触发一项" if count == 1 else f"随机触发{count}项"
        return (f"{draw}{replacement}：" + " / ".join(summaries),)
    if ability == "遍历目标":
        target = node.get("目标")
        target_text = "目标"
        if isinstance(target, Mapping):
            target_text = _target(target)
        effects = node.get("效果")
        lines = []
        if isinstance(effects, Sequence) and not isinstance(effects, (str, bytes)):
            for effect in effects:
                if isinstance(effect, Mapping):
                    for line in _combat_lines(effect, related):
                        if line.startswith("对当前目标"):
                            lines.append(
                                f"对{target_text}" + line.removeprefix("对当前目标")
                            )
                        elif line.startswith("当前目标"):
                            lines.append(target_text + line.removeprefix("当前目标"))
                        else:
                            lines.append(f"对{target_text}：{line}")
        return tuple(lines)
    if ability == "重复执行":
        body = "；".join(_nodes(node.get("效果"), related))
        return (f"重复{_value(node.get('次数'))}次：{body}",)
    if ability == "尝试执行":
        attempt = "；".join(_nodes(node.get("尝试效果"), related))
        success = "；".join(_nodes(node.get("成功效果"), related))
        failure = "；".join(_nodes(node.get("失败效果"), related))
        text = f"先处理：{attempt or '指定效果'}"
        if success:
            text += f"；处理成功后：{success}"
        if failure:
            text += f"；处理未成功时：{failure}"
        return (text,)
    if ability == "事务执行":
        body = "；".join(_nodes(node.get("效果"), related))
        failure = "；".join(_nodes(node.get("失败效果"), related))
        text = f"依次处理：{body or '指定效果'}"
        text += "；任一步骤失败，本项不成立并回退已处理的改变"
        if failure:
            text += f"；回退后：{failure}"
        return (text,)
    if ability == "监听事件":
        event = str(node.get("事件") or "对应时机")
        relation = str(node.get("阵营关系") or "")
        subject = {
            "自身": "自身",
            "任意敌方": "任意敌方",
            "任意友方": "任意友方",
        }.get(relation, relation or "相关角色")
        effects = node.get("效果")
        summaries: list[str] = []
        if isinstance(effects, Sequence) and not isinstance(effects, (str, bytes)):
            for effect in effects:
                if isinstance(effect, Mapping):
                    summaries.extend(_combat_lines(effect, related))
        timing = (
            "的召唤物或构造物入场后"
            if event == "战斗对象入场后"
            else event
            if event.endswith(("前", "后", "时"))
            else f"{event}时"
        )
        cap = _trigger_limit_suffix(node)
        condition = _conditions(node.get("条件"))
        requirement = f"，且{condition}" if condition != "条件成立" else ""
        effect_text = "；".join(summaries) or "不产生额外效果"
        return (f"{subject}{timing}{requirement}：{effect_text}{cap}",)
    if ability in {
        "读取数值",
        "计算数值",
        "随机数值",
        "聚合数值",
        "选择目标",
        "选择技能",
        "选择状态",
        "概率条件",
        "数值条件",
        "状态条件",
        "类型条件",
        "组合条件",
        "标签条件",
    }:
        if ability.startswith("选择"):
            return (
                {"选择目标": _target, "选择技能": _skill, "选择状态": _status}[ability](
                    node
                ),
            )
        if ability.endswith("条件"):
            return (_condition(node),)
        return (_value(node),)
    if ability == "造成伤害":
        value = node.get("数值")
        amount = _amount(value)
        target = _target(node.get("目标"))
        elements = node.get("属性构成")
        element_text = ""
        if isinstance(elements, Mapping) and elements:
            element_text = (
                "（"
                + "、".join(f"{key}{value}%" for key, value in elements.items())
                + "）"
            )
        traits = []
        for key, label in (
            ("能否闪避", "可闪避"),
            ("能否暴击", "可暴击"),
            ("能否格挡", "可格挡"),
        ):
            if node.get(key):
                traits.append(label)
        trait_text = f"，{'、'.join(traits)}" if traits else ""
        defense_rule = str(node.get("防御规则") or "")
        damage_type = "真实伤害" if defense_rule == "真实" else "伤害"
        return (f"对{target}造成{amount}{element_text}{damage_type}{trait_text}",)
    if ability == "恢复资源":
        return (
            (
                f"{_target(node.get('目标'))}恢复"
                f"{_resource_amount(node.get('数值'), node.get('资源', '资源'))}"
            ),
        )
    if ability == "消耗资源":
        return (
            (
                f"{_target(node.get('目标'))}消耗"
                f"{_resource_amount(node.get('数值'), node.get('资源', '资源'))}"
            ),
        )
    if ability == "支付代价":
        kind = str(node.get("代价类型") or "代价")
        failure = "，不足则无法施展" if node.get("不足时是否失败") else ""
        if kind == "资源":
            return (
                (
                    f"消耗{_target(node.get('目标'))}的"
                    f"{_resource_amount(node.get('数值'), node.get('资源', '资源'))}"
                    f"{failure}"
                ),
            )
        if kind == "状态层数":
            return (
                f"消耗{_status(node.get('状态'))}{_value(node.get('数值'))}层{failure}",
            )
        if kind == "行动条":
            return (
                f"令{_target(node.get('目标'))}行动延后{_value(node.get('数值'))}点{failure}",
            )
        if kind == "技能冷却":
            return (
                (
                    f"令{_target(node.get('目标'))}的{_skill(node.get('技能'))}"
                    f"增加{_value(node.get('数值'))}次行动冷却{failure}"
                ),
            )
        return (f"支付{kind}{failure}",)
    if ability == "设置资源":
        return (
            (
                f"将{_target(node.get('目标'))}的{node.get('资源', '资源')}设为"
                f"{_resource_amount(node.get('数值'), node.get('资源', '资源'))}"
            ),
        )
    if ability == "转移资源":
        return (
            (
                f"从{_target(node.get('来源目标'))}向{_target(node.get('接收目标'))}"
                f"转移{_resource_amount(node.get('数值'), node.get('来源资源', '资源'))}"
            ),
        )
    if ability == "添加状态":
        state = node.get("状态")
        if not isinstance(state, Mapping):
            return (f"{_target(node.get('目标'))}获得状态",)
        name = str(state.get("名称") or "未名状态")
        duration = state.get("剩余行动")
        suffix = f"，持续{duration}次行动" if duration is not None else ""
        attributes = state.get("属性")
        if isinstance(attributes, Mapping) and attributes:
            changes = "、".join(
                f"{key}{_signed('增加' if float(value) >= 0 else '减少', abs(value))}"
                for key, value in attributes.items()
                if isinstance(value, (int, float))
            )
            if changes:
                suffix += f"（{changes}）"
        stacks = state.get("层数上限")
        if stacks is not None:
            suffix += f"，最多{stacks}层"
        return (f"{_target(node.get('目标'))}获得“{name}”{suffix}",)
    if ability in {"移除状态", "增加状态层数", "消耗状态层数", "延长状态", "缩短状态"}:
        state = _status(node.get("状态"))
        if ability == "移除状态":
            return (f"移除{state}",)
        if ability == "增加状态层数":
            return (f"令{state}增加{node.get('层数', 1)}层",)
        if ability == "消耗状态层数":
            return (f"消耗{state}{node.get('层数', 1)}层",)
        direction = "延长" if ability == "延长状态" else "缩短"
        return (f"令{state}{direction}{node.get('持续数值', '')}次行动",)
    if ability in {"复制状态", "转移状态"}:
        verb = "复制" if ability == "复制状态" else "转移"
        return (
            f"将{_status(node.get('状态'))}{verb}给{_target(node.get('接收目标'))}",
        )
    if ability == "修改行动条":
        method = "提前" if node.get("方式") == "增加" else "延后"
        return (
            f"令{_target(node.get('目标'))}行动{method}{_value(node.get('数值'))}点",
        )
    if ability == "修改技能冷却":
        method = {"增加": "延长", "减少": "缩短", "设置": "设为"}.get(
            str(node.get("方式") or ""), "改变"
        )
        return (
            f"令{_target(node.get('目标'))}的{_skill(node.get('技能'))}冷却{method}{_value(node.get('数值'))}次行动",
        )
    if ability == "修改机制计量":
        method = str(node.get("方式") or "改变")
        value = _value(node.get("数值", ""))
        raw_counter = _display_name(node.get("计量") or "效果")
        counter = {"分伤": "伤害分担强度"}.get(raw_counter, raw_counter)
        limit = node.get("最高值")
        suffix = (
            f"（上限{limit}）" if isinstance(limit, (int, float)) and limit < 999 else ""
        )
        target = _target(node.get("目标"))
        prefix = "" if target == "自身" else target
        return (f"{prefix}{counter}{_change(method, value)}{suffix}",)
    if ability == "追加攻击":
        return (
            f"对{_target(node.get('目标'))}追加一次{node.get('威力倍率', 1)}倍威力攻击",
        )
    if ability == "分摊伤害":
        return (f"由{_target(node.get('目标'))}分摊{node.get('比例', 0)}%伤害",)
    if ability == "转移伤害":
        return (f"将{_amount(node.get('数值'))}伤害转给{_target(node.get('目标'))}",)
    if ability == "抵挡致命伤害":
        return (f"抵挡一次致命伤害，并至少保留{node.get('保留血气', 1)}点血气",)
    if ability == "复活":
        return (
            f"复活{_target(node.get('目标'))}，恢复{node.get('血气百分比', 10)}%血气与{node.get('精神百分比', 0)}%精神",
        )
    if ability == "修改事件数值":
        return (f"令本次效果数值{_change(node.get('方式'), _value(node.get('数值')))}",)
    if ability == "修改事件目标":
        return (f"令本次效果改为作用于{_target(node.get('目标'))}",)
    if ability == "修改事件标签":
        return (
            f"为本次效果{node.get('方式', '添加')}标签：{'、'.join(map(str, node.get('标签') or ()))}",
        )
    if ability == "取消事件":
        return ("取消本次效果",)
    if ability == "触发技能":
        exemptions = []
        if node.get("忽略代价"):
            exemptions.append("不消耗精神")
        if node.get("忽略冷却"):
            exemptions.append("无视冷却")
        suffix = f"（{'、'.join(exemptions)}）" if exemptions else ""
        return (
            f"立即对{_target(node.get('目标'))}施展{_skill(node.get('技能'))}{suffix}",
        )
    if ability == "记录战斗事实":
        name = str(node.get("名称") or "战斗记录")
        value = node.get("值")
        mode = str(node.get("方式") or "覆盖")
        value_text = _value(value)
        action = {
            "覆盖": "覆盖保存",
            "累加": "累计保存",
        }.get(mode, f"按{mode}保存")
        retained = node.get("保留数量")
        suffix = f"，最多保留{retained}条" if retained is not None else ""
        return (f"将{value_text or '本次事件数值'}{action}为“{name}”{suffix}",)
    if ability == "保存结果":
        name = str(node.get("名称") or "临时结果")
        source = str(node.get("来源") or "上个效果")
        value = node.get("值")
        if value is not None:
            return (f"将{_value(value) or '指定值'}保存为“{name}”",)
        return (f"保存{source}的结果为“{name}”，供后续效果读取",)
    if ability == "修改战斗关联":
        method = "建立" if node.get("方式") == "建立" else "解除"
        left = _target(node.get("一方"))
        right = _target(node.get("另一方"))
        subject = "" if left == "自身" else left
        return (f"{subject}与{right}{method}“{node.get('名称', '战斗')}”关联",)
    if ability == "修改技能":
        field = {"精神消耗": "精神消耗", "冷却行动": "冷却"}.get(
            str(node.get("字段") or ""), str(node.get("字段") or "技能数值")
        )
        skill = _skill(node.get("技能"))
        if node.get("字段") == "禁用" and isinstance(node.get("值"), bool):
            state = "无法施展" if node["值"] else "恢复施展"
            return (f"令{_target(node.get('目标'))}的{skill}{state}",)
        return (
            (
                f"令{_target(node.get('目标'))}{skill}的{field}"
                f"{_signed(node.get('方式'), node.get('值'))}"
            ),
        )
    if ability == "复制技能":
        return (
            (
                f"将{_target(node.get('来源目标'))}的{_skill(node.get('技能'))}"
                f"复制给{_target(node.get('接收目标'))}，"
                f"记作“{node.get('名称', '复制技能')}”"
            ),
        )
    if ability == "修改行动意图":
        if node.get("字段") == "目标":
            return (f"令行动目标改为{_target(node.get('目标'))}",)
        return (f"改变行动意图中的{node.get('字段', '选择')}",)
    if ability == "转化事件":
        return (f"将本次效果转化为“{node.get('事件', '另一效果')}”",)
    if ability == "修改判定":
        return (
            f"令接下来{node.get('次数', 1)}次{node.get('判定', '判定')}{node.get('方式', '生效')}",
        )
    if ability == "修改战场规则":
        name = str(node.get("名称") or "战场规则")
        rule = node.get("规则")
        listeners = rule.get("监听") if isinstance(rule, Mapping) else ()
        detail = "；".join(_nodes(listeners, related))
        suffix = f"：{detail}" if detail else ""
        return (f"{node.get('方式', '添加')}战场规则“{name}”{suffix}",)
    if ability == "切换形态":
        definition = node.get("定义")
        changes = ""
        if isinstance(definition, Mapping):
            attributes = definition.get("属性变化")
            if isinstance(attributes, Mapping):
                changes = (
                    "（"
                    + "、".join(
                        f"{key}{_signed('增加' if value >= 0 else '减少', abs(value))}"
                        for key, value in attributes.items()
                        if isinstance(value, (int, float))
                    )
                    + "）"
                )
        target = _target(node.get("目标"))
        prefix = "进入" if target == "自身" else f"令{target}进入"
        return (f"{prefix}“{node.get('形态', '新形态')}”{changes}",)
    if ability == "创建战斗对象":
        definition = node.get("定义")
        if not isinstance(definition, Mapping):
            return (f"创建一个{node.get('类型', '战斗对象')}",)
        details = []
        if definition.get("耐久") is not None:
            details.append(f"耐久{definition['耐久']}")
        if definition.get("持续行动") is not None:
            details.append(f"持续{definition['持续行动']}次行动")
        listeners = "；".join(_nodes(definition.get("监听"), related))
        if listeners:
            details.append(listeners)
        suffix = f"：{'；'.join(details)}" if details else ""
        return (
            f"召出{node.get('类型', '战斗对象')}“{definition.get('名称', '未名造物')}”{suffix}",
        )
    if ability == "移除战斗对象":
        object_id = _value(node.get("对象ID"))
        return (
            (
                f"移除战斗对象“{object_id}”"
                if object_id
                else "移除自身全部召唤物与构造物"
            ),
        )
    if ability == "修改归属":
        return (
            f"将{_target(node.get('目标'))}的{node.get('字段', '归属')}改为{node.get('阵营') or _target(node.get('归属目标'))}",
        )
    if ability == "回放效果":
        return (f"以{node.get('倍率', 1)}倍强度再次施展{node.get('范围', '上个效果')}",)
    if ability == "修改战术":
        tactics = node.get("战术")
        arrangements: list[str] = []
        if isinstance(tactics, Sequence) and not isinstance(tactics, (str, bytes)):
            for tactic in tactics:
                if isinstance(tactic, Mapping):
                    action = str(tactic.get("行动") or "行动")
                    sorting = str(tactic.get("目标排序") or "默认目标")
                    arrangements.append(f"{action}（{sorting}目标）")
        return (
            f"将{_target(node.get('目标'))}的战术{node.get('方式', '调整')}为"
            + "、".join(arrangements),
        )
    if ability in {"引用战斗机制", "引用被动机制"}:
        return ()
    return ()


def _nodes(
    value: object, related: Mapping[str, object] | None = None
) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        return _combat_lines(value, related)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(
        line
        for node in value
        if isinstance(node, Mapping)
        for line in _combat_lines(node, related)
        if line
    )


def _conditions(value: object) -> str:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return "条件成立"
    conditions = [_condition(node) for node in value if isinstance(node, Mapping)]
    return "且".join(item for item in conditions if item) or "条件成立"


def _condition(node: Mapping[str, object]) -> str:
    ability = str(node.get("能力") or "")
    if ability == "概率条件":
        return f"有{_value(node.get('概率'))}%概率"
    if ability == "数值条件":
        return f"{_value(node.get('左值'))}{node.get('比较', '等于')}{_value(node.get('右值'))}"
    if ability == "状态条件":
        state = str(node.get("状态") or "指定状态")
        comparison = str(node.get("比较") or "存在")
        stacks = node.get("层数")
        suffix = (
            f"{stacks}层"
            if stacks is not None and comparison not in {"存在", "不存在"}
            else ""
        )
        return f"{_target(node.get('目标'))}的“{state}”{comparison}{suffix}"
    if ability == "类型条件":
        return f"{node.get('对象', '目标')}的{node.get('类型', '类型')}为{node.get('值', '')}"
    if ability == "组合条件":
        children = node.get("条件")
        values = []
        if isinstance(children, Sequence) and not isinstance(children, (str, bytes)):
            values = [
                _condition(value) for value in children if isinstance(value, Mapping)
            ]
        relation = str(node.get("关系") or "全部成立")
        separator = "或" if relation == "任一成立" else "且"
        result = separator.join(values)
        return f"不满足（{result}）" if relation == "全部不成立" else f"（{result}）"
    if ability == "标签条件":
        labels = "、".join(map(str, node.get("标签") or ()))
        relation = str(node.get("关系") or "包含任一")
        if relation == "为空":
            return f"{node.get('对象', '目标')}没有标签"
        if relation == "数量至少":
            return f"{node.get('对象', '目标')}至少有{node.get('数量', 1)}个指定标签"
        return f"{node.get('对象', '目标')}标签{relation}“{labels}”"
    return "条件成立"


def _target(value: object) -> str:
    if not isinstance(value, Mapping):
        return "自身"
    scope = str(value.get("范围") or "目标")
    label = {
        "自身": "自身",
        "当前目标": "当前目标",
        "敌方": "敌方",
        "己方": "己方",
        "全体": "战场全体",
        "效果来源": "效果来源",
        "事件来源": "事件来源",
        "事件承受者": "事件承受者",
        "行动者": "当前行动者",
        "关联对象": "关联对象",
        "主人": "主人",
        "控制者": "控制者",
    }.get(scope, scope)
    if value.get("选择全部"):
        label += "全体"
    else:
        count = value.get("数量")
        if isinstance(count, int) and count > 1:
            label = f"{count}名{label}"
        elif scope in {"敌方", "己方", "全体"}:
            label = f"一名{label}"
    sorting = str(value.get("排序") or "默认")
    sorting_text = {
        "随机": "随机",
        "血气比例从低到高": "血气比例最低",
        "血气比例从高到低": "血气比例最高",
        "速度从高到低": "速度最高",
        "行动条从高到低": "最先行动",
    }.get(sorting, "")
    if sorting_text:
        label += f"（{sorting_text}）"
    if value.get("排除自身"):
        label += "（不含自身）"
    if value.get("生存状态") == "死亡":
        label = "已阵亡的" + label
    return label


def _skill(value: object) -> str:
    if not isinstance(value, Mapping):
        return "技能"
    scope = str(value.get("范围") or "技能")
    name = str(value.get("名称") or "")
    if scope == "指定技能" and name:
        return f"“{name}”"
    label = {
        "全部技能": "技能",
        "当前技能": "当前技能",
        "可用技能": "可用技能",
        "冷却中的技能": "冷却中的技能",
    }.get(scope, scope)
    if scope == "当前技能":
        return label
    if value.get("选择全部"):
        return "全部" + label
    count = value.get("数量")
    prefix = f"{count}门" if isinstance(count, int) and count > 1 else "一门"
    sorting = str(value.get("排序") or "无")
    sorting_text = {
        "随机": "随机",
        "冷却从低到高": "冷却最低的",
        "冷却从高到低": "冷却最高的",
        "释放顺序": "释放顺序最前的",
    }.get(sorting, "")
    return sorting_text + prefix + label


def _status(value: object) -> str:
    if isinstance(value, str):
        return f"“{value}”"
    if not isinstance(value, Mapping):
        return "指定状态"
    target = _target(value.get("目标")) if value.get("目标") is not None else ""
    name = str(value.get("名称") or "")
    category = str(value.get("分类") or "")
    labels = "、".join(map(str, value.get("标签") or ()))
    identity = f"“{name}”" if name else f"{category}状态" if category else "状态"
    if labels:
        identity += f"（{labels}）"
    if value.get("选择全部"):
        identity = "全部" + identity
    return target + identity


def _value(value: object) -> str:
    if isinstance(value, Mapping):
        ability = str(value.get("能力") or "")
        if ability == "读取数值":
            source = str(value.get("来源") or "数值")
            target = _target(value.get("目标")) if value.get("目标") is not None else ""
            label = {
                "自身属性": f"自身{value.get('属性', '属性')}",
                "目标属性": f"目标{value.get('属性', '属性')}",
                "效果来源属性": f"效果来源的{value.get('属性', '属性')}",
                "机制计量": f"{target}{value.get('计量', '机制计量')}",
                "事件事实": f"本次{value.get('事实', '事件数值')}",
                "战斗记录": f"战斗记录“{value.get('名称', '')}”",
                "状态层数": f"{target}“{value.get('状态', '')}”层数",
                "保存结果": f"已保存的“{value.get('名称', '结果')}”",
                "行动条": f"{target}行动进度",
                "自身当前血气": "自身当前血气",
                "自身已损失血气": "自身已损失血气",
                "目标当前血气": "目标当前血气",
                "目标已损失血气": "目标已损失血气",
                "自身当前精神": "自身当前精神",
                "目标当前精神": "目标当前精神",
                "目标已损失精神": "目标已损失精神",
                "自身当前护盾": "自身当前护盾",
                "目标当前护盾": "目标当前护盾",
            }.get(source, source.replace("自身", "自身的").replace("目标", "目标的"))
            percent = value.get("百分比", 100)
            return f"{label}{percent}%" if percent != 100 else label
        if ability == "计算数值":
            operators = {
                "相加": "+",
                "相减": "-",
                "相乘": "×",
                "相除": "÷",
                "取余": "取余",
                "乘方": "的次方",
                "取小": "与二者较小值",
                "取大": "与二者较大值",
            }
            operator = operators.get(
                str(value.get("方式") or ""), str(value.get("方式") or "计算")
            )
            return (
                f"（{_value(value.get('左值'))}{operator}{_value(value.get('右值'))}）"
            )
        if ability == "随机数值":
            return f"{value.get('最低值', 0)}至{value.get('最高值', 0)}之间的随机数"
        if ability == "聚合数值":
            method = str(value.get("方式") or "数量")
            if method == "数量":
                return f"{_target(value.get('目标'))}的数量"
            return (
                f"{_target(value.get('目标'))}中{_value(value.get('数值'))}的{method}"
            )
        attribute = value.get("属性")
        percent = value.get("百分比")
        fixed = value.get("固定值")
        if attribute is not None and percent is not None:
            return f"{attribute}的{percent}%"
        if fixed is not None:
            return str(fixed)
    return str(value if value is not None else "")


def _amount(value: object) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value}点"
    text = _value(value)
    return f"相当于{text}的" if text else ""


def _resource_amount(value: object, resource: object) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value}点{resource}"
    text = _value(value)
    return f"相当于{text}的{resource}" if text else str(resource)


def _change(method: object, value: object) -> str:
    normalized = str(method or "")
    if normalized == "增加":
        return f"+{value}"
    if normalized == "减少":
        return f"-{value}"
    if normalized == "设置":
        return f"设为{value}"
    if normalized == "清空":
        return "清零"
    if normalized in {"乘算", "乘以百分比"}:
        return f"变为原本的{value}%"
    if normalized:
        return f"{normalized}{value}"
    return str(value)


def _trigger_limit_suffix(node: Mapping[str, object]) -> str:
    """把节点级触发上限统一写成玩家可判断的限制。"""

    limits: list[str] = []
    per_action = node.get("每次行动最多触发")
    if isinstance(per_action, (int, float)) and not isinstance(per_action, bool) and per_action > 0:
        limits.append(f"每行动限{_display_number(float(per_action))}次")
    per_battle = node.get("每场战斗最多触发")
    if isinstance(per_battle, (int, float)) and not isinstance(per_battle, bool) and per_battle > 0:
        limits.append(f"每战限{_display_number(float(per_battle))}次")
    return f"，{'，'.join(limits)}" if limits else ""
