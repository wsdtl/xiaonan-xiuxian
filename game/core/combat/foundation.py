"""加载战斗基石与统一时序契约；具体构筑仍在战斗请求中解析。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from game.core.data import JsonDataService, materialize
from game.core.formation import FormationNodeRules

from .executors import EXECUTOR_CATEGORIES
from .rules import validate_rule_layer
from .schema import RuleSchemaValidator

#: 属性口径：引擎**怎么读**这个属性。基准就是属性自己的 `默认值`
#: （读法见 `models.attribute_ratio`），这张表只声明用法。
#:
#: 这里必须写死在代码里的是「有哪几种口径」，因为引擎按口径分派；**具体某个属性是哪一种**
#: 是内容决定，所以写在 `属性.json` 的 `口径` 字段里。
ATTRIBUTE_CALIBERS: Mapping[str, str] = {
    "数值": "直接参与加减与曲线（攻击、防御、速度、各类上限、固定穿透、行动开始恢复）",
    "加成": "相对倍率：基准 100 即不增不减，卡面写 120 就是 +20%",
    "倍率": "本身就是倍率：暴击伤害 150 = ×1.5，连击伤害 100 = ×1.0",
    "概率": "百分点概率，0 = 不发生；命中率自己那条是 100 = 必中",
    "减免": "从倍率里减去的百分点，0 = 不减免",
    "比率": "直接当比率用（比例穿透），0 = 不生效",
}

#: 「加成」类只能有 100 这一种基准，「减免 / 比率」类只能有 0 这一种基准。
#: 混用会静默改机制：实测把减免类的基准也补成 100，`伤害减免` 就变成「减 100%」，
#: 1967 场里 1950 场战报变化——这不是等价改写。所以在这里锁死。
_BASELINE_IS_100 = ("加成",)
_BASELINE_IS_ZERO = ("减免", "比率")

#: `时序.事件监听.排序` 的**唯一出处**：数据里那张单子的**先后**，就是战斗核心拼监听排序键的先后。
#: `mechanics.py` 的 `_ListenerSink.add` 照它拼键、`_passive_listener_entries` 照它按位次重拼
#: （下标由这张单子算出来，不写字面量），所以**加减字段时只改这一处、另一处跟着走**。
#:
#: 这里按**顺序逐字**校验，不只是比集合：顺序错了不会抛错，只会静默换掉结算先后——同一事件上
#: 两个监听谁先结算决定结果（见 `规则/说明.md` 的「监听优先级」），所以必须在启动期就挡住。
EVENT_LISTENER_SORT_ORDER: tuple[str, ...] = (
    "响应等级降序",
    "来源层级升序",
    "监听优先级降序",
    "结算顺序升序",
    "参战位序",
    "装配位序",
    "物品编号",
    "能力序号",
)


def load_battle_foundation(
    data: JsonDataService,
    *,
    formation_rules: FormationNodeRules | None = None,
    templates: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if not data.status().loaded:
        raise RuntimeError("JSON 数据微服务必须先于战斗微服务启动")
    result = materialize(data.dataset("战斗定义"))
    rules = materialize(data.dataset("战斗规则"))
    result.update(
        {
            "伤害规则": rules["伤害"],
            "地形节奏": rules["地形"],
            "行动规则": rules["行动"],
            "时序": rules["时序"],
            "状态反应": rules["状态反应"],
            "环境规则": rules["环境"],
            "五行": rules["五行"],
            "战场环境": {
                environment_id: materialize(value)
                for environment_id, value in data.entities("战场环境").items()
            },
            "阵法规则": formation_rules,
        }
    )
    validate_battle_foundation(result, templates=templates)
    result["构筑模板库"] = dict(templates or {})
    return result


def _validate_event_bound_abilities(
    value: Any,
    path: str,
    *,
    damage_event: bool = False,
) -> None:
    if isinstance(value, Mapping):
        ability = str(value.get("能力") or "")
        current_damage_event = damage_event
        if ability == "监听事件":
            current_damage_event = str(value.get("事件") or "") in {
                "造成伤害前",
                "受到致命伤害",
            }
        if ability == "转移伤害" and not current_damage_event:
            raise ValueError(f"{path}.转移伤害只能在伤害事件监听中执行")
        for key, child in value.items():
            _validate_event_bound_abilities(
                child,
                f"{path}.{key}",
                damage_event=current_damage_event,
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_event_bound_abilities(
                child,
                f"{path}[{index}]",
                damage_event=damage_event,
            )


def rule_validator(value: Mapping[str, Any]) -> RuleSchemaValidator:
    """按战斗定义装配一份能力节点校验器；构筑与定义共用同一份词汇表。"""

    return RuleSchemaValidator(
        abilities=_mapping(value.get("原子能力"), "原子能力"),
        executor_categories=EXECUTOR_CATEGORIES,
        attributes=_mapping(value.get("属性"), "属性"),
        resources=_mapping(value.get("资源"), "资源"),
        events=_mapping(value.get("事件"), "事件"),
    )


def validate_battle_foundation(
    value: Mapping[str, Any],
    *,
    templates: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    abilities = _mapping(value.get("原子能力"), "原子能力")
    events = _mapping(value.get("事件"), "事件")
    attributes = _mapping(value.get("属性"), "属性")
    _validate_attribute_definitions(attributes)
    resources = _mapping(value.get("资源"), "资源")
    action_rules = _mapping(value.get("行动规则"), "行动规则")
    timing = _mapping(value.get("时序"), "时序")
    damage_rules = _mapping(value.get("伤害规则"), "伤害规则")
    status_reactions = value.get("状态反应")
    environments = _mapping(value.get("战场环境") or {}, "战场环境")
    formation_rules = value.get("阵法规则")
    environment_rules = _mapping(value.get("环境规则"), "环境规则")
    five_elements = _mapping(value.get("五行"), "五行")
    _validate_five_elements(five_elements)
    _validate_action_rules(action_rules, attributes, resources)
    _validate_timing(timing)
    _validate_damage_rules(damage_rules)
    _validate_environment_rules(environment_rules, events)
    for name, raw in events.items():
        definition = _mapping(raw, f"事件.{name}")
        unknown = set(definition) - {"携带事实", "可修改"}
        if unknown:
            raise ValueError(f"事件.{name}存在未知字段：{'、'.join(sorted(unknown))}")
        facts = _strings(definition.get("携带事实"), f"事件.{name}.携带事实")
        mutable = _strings(definition.get("可修改"), f"事件.{name}.可修改")
        if not set(mutable) <= {"当前数值", "目标", "标签", "取消", "类型"}:
            raise ValueError(f"事件.{name}.可修改包含核心不认识的操作")
        if len(facts) != len(set(facts)) or len(mutable) != len(set(mutable)):
            raise ValueError(f"事件.{name}的事实或修改项不能重复")
        if "类型" in mutable and name not in {"恢复前", "获得护盾前", "资源恢复前"}:
            raise ValueError(f"事件.{name}没有可转化的共同结算语义")
    validator = rule_validator(value)
    # 校验器要认识构筑模板：卡里的 `{"模板": …}` 引用没有 `能力` 字段，
    # 不展开就会被当成非法节点挡掉（实测会让启动失败）。
    validator.templates = dict(templates or {})
    validator.validate_definitions("战斗定义.原子能力")
    validate_rule_layer(value.get("规则层") or {}, abilities, validator)
    _validate_rule_text_carrier(abilities)
    _validate_battle_environments(environments, validator)
    if not isinstance(formation_rules, FormationNodeRules):
        raise TypeError("战斗核心缺少阵法节点运行契约")
    _validate_formation_node_rules(formation_rules)
    _validate_status_reactions(status_reactions, validator)
    declared = {
        str(definition.get("执行器") or "") for definition in abilities.values()
    }
    missing = set(EXECUTOR_CATEGORIES) - declared
    if missing:
        raise ValueError(f"执行器没有原子能力声明：{'、'.join(sorted(missing))}")


def _validate_rule_text_carrier(abilities: Mapping[str, Any]) -> None:
    """规则文本只做载体这一件事：它存在，且带着 `规则` 字段。

    「规则文本只能挂在卡面根部」不在这里判：装配执行器只在根部被查表，
    嵌进效果里会直接撞上「未实现装配执行器」，那是响的。
    """

    from .rules import RULE_FIELD, RULE_TEXT_ABILITY

    definition = abilities.get(RULE_TEXT_ABILITY)
    if not isinstance(definition, Mapping):
        raise ValueError(f"原子能力缺少规则文本载体：{RULE_TEXT_ABILITY}")
    fields = _mapping(definition.get("字段") or {}, f"原子能力.{RULE_TEXT_ABILITY}.字段")
    if RULE_FIELD not in fields:
        raise ValueError(f"原子能力.{RULE_TEXT_ABILITY}必须声明 {RULE_FIELD} 字段")


def _validate_attribute_definitions(attributes: Mapping[str, Any]) -> None:
    """每个属性必须声明它怎么被读，且基准与口径相符。

    这是「补上缺失定义」的那一条：改动前属性的读法只存在于调用点的 `1 + …` / `- …` 里，
    同一张表要对着代码看才知道「伤害加成 20」是 +20% 还是「设成 20%」。
    """

    for name, raw in attributes.items():
        path = f"属性.{name}"
        definition = _mapping(raw, path)
        unknown = set(definition) - {
            "默认值", "单位", "最小单位", "最低值", "最高值", "显示", "口径", "说明",
        }
        if unknown:
            raise ValueError(f"{path}存在未知字段：{'、'.join(sorted(unknown))}")
        for field in ("默认值", "最低值", "最高值", "口径"):
            if field not in definition:
                raise ValueError(f"{path}缺少字段：{field}")
        caliber = str(definition["口径"] or "")
        if caliber not in ATTRIBUTE_CALIBERS:
            raise ValueError(
                f"{path}.口径未登记：{caliber or '<空>'}；"
                f"可选 {'、'.join(ATTRIBUTE_CALIBERS)}"
            )
        default = float(definition["默认值"])
        if caliber in _BASELINE_IS_100 and default != 100.0:
            raise ValueError(f"{path}是{caliber}口径，基准必须是 100，当前 {default:g}")
        if caliber in _BASELINE_IS_ZERO and default != 0.0:
            raise ValueError(f"{path}是{caliber}口径，基准必须是 0，当前 {default:g}")
        if not float(definition["最低值"]) <= default <= float(definition["最高值"]):
            raise ValueError(
                f"{path}的默认值 {default:g} 不在上下限 "
                f"{float(definition['最低值']):g}~{float(definition['最高值']):g} 内"
            )


def _validate_battle_environments(
    environments: Mapping[str, Any],
    validator: RuleSchemaValidator,
) -> None:
    if not environments:
        raise ValueError("战场环境不能为空")
    names: set[str] = set()
    for environment_id, raw in environments.items():
        path = f"战场环境[{environment_id}]"
        environment = _mapping(raw, path)
        unknown = set(environment) - {"编号", "名称", "说明", "阶段"}
        if unknown:
            raise ValueError(f"{path}存在未知字段：{'、'.join(sorted(unknown))}")
        if str(environment.get("编号") or "") != environment_id:
            raise ValueError(f"{path}.编号与数据索引不一致")
        name = str(environment.get("名称") or "").strip()
        if not name or name in names:
            raise ValueError(f"战场环境名称为空或重复：{name or '<空>'}")
        names.add(name)
        stages = environment.get("阶段")
        if not isinstance(stages, list) or not stages:
            raise ValueError(f"{path}.阶段必须是非空数组")
        previous = -1.0
        stage_names: set[str] = set()
        for index, raw_stage in enumerate(stages):
            stage_path = f"{path}.阶段[{index}]"
            stage = _mapping(raw_stage, stage_path)
            unknown = set(stage) - {
                "名称",
                "起始承伤比例",
                "入阶能力",
                "常驻能力",
            }
            if unknown:
                raise ValueError(
                    f"{stage_path}存在未知字段：{'、'.join(sorted(unknown))}"
                )

            stage_name = str(stage.get("名称") or "").strip()
            if not stage_name or stage_name in stage_names:
                raise ValueError(f"{stage_path}.名称为空或重复")
            stage_names.add(stage_name)
            threshold = stage.get("起始承伤比例")
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
                raise TypeError(f"{stage_path}.起始承伤比例必须是数字")
            threshold = float(threshold)
            if (
                threshold < 0
                or (index == 0 and threshold != 0)
                or threshold <= previous
            ):
                raise ValueError(f"{stage_path}.起始承伤比例必须从 0 严格递增")
            previous = threshold
            entries = stage.get("入阶能力")
            listeners = stage.get("常驻能力")
            if not isinstance(entries, list) or not isinstance(listeners, list):
                raise TypeError(f"{stage_path}的能力必须使用数组")
            for ability_index, node in enumerate(entries):
                validator.validate_node(
                    node,
                    f"{stage_path}.入阶能力[{ability_index}]",
                    allowed_categories={"组合", "引用", "效果"},
                )
                _validate_neutral_environment_node(
                    node, f"{stage_path}.入阶能力[{ability_index}]"
                )
            for ability_index, node in enumerate(listeners):
                validator.validate_node(
                    node,
                    f"{stage_path}.常驻能力[{ability_index}]",
                    allowed_abilities={"监听事件"},
                )
                _validate_neutral_environment_node(
                    node, f"{stage_path}.常驻能力[{ability_index}]"
                )


def _validate_five_elements(value: Mapping[str, Any]) -> None:
    expected = {
        "属性集合", "根性字段", "效果字段", "根性来源", "无相规则",
        "相生", "相克", "倍率", "根性倍率", "团队协同", "根性生成", "实体属性",
    }
    if set(value) != expected:
        raise ValueError("五行规则字段必须完整且不能包含额外字段")
    if value["属性集合"] != ["木", "火", "土", "金", "水", "无相"]:
        raise ValueError("五行属性集合必须固定为木火土金水无相")
    if value["根性字段"] != "五行根性" or value["效果字段"] != "属性构成":
        raise ValueError("五行字段名称不符合统一契约")
    if value["根性来源"] != ["人物", "道侣实例", "灵兽", "敌方修士"]:
        raise ValueError("五行根性来源必须覆盖人物、道侣实例、灵兽和敌方修士")
    if value["无相规则"] != "固定中性":
        raise ValueError("无相规则不符合统一契约")
    _validate_relation_pairs(value["相生"], "相生")
    _validate_relation_pairs(value["相克"], "相克")
    multipliers = _mapping(value["倍率"], "五行.倍率")
    for name in ("相生", "相克", "被克", "同属性", "无关", "无相", "团队相生"):
        if not isinstance(multipliers.get(name), (int, float)):
            raise TypeError(f"五行.倍率.{name}必须是数字")
    root = _mapping(value["根性倍率"], "五行.根性倍率")
    if any(not isinstance(root.get(name), (int, float)) for name in ("基准", "每点修正", "最低", "最高")):
        raise ValueError("五行.根性倍率字段不完整")
    generation = _mapping(value["根性生成"], "五行.根性生成")
    if generation.get("算法") != "主次定值" or generation.get("总和") != 100:
        raise ValueError("五行根性生成规则不符合统一契约")
    entity = _mapping(value["实体属性"], "五行.实体属性")
    if entity.get("字段") != "属性构成" or entity.get("来源类别") != ["功法", "真意", "气机", "器律"]:
        raise ValueError("五行实体属性规则不符合统一契约")


def _validate_relation_pairs(value: Any, label: str) -> None:
    if not isinstance(value, list) or len(value) != 5:
        raise ValueError(f"五行.{label}必须有五条关系")
    pairs = set()
    for index, raw in enumerate(value):
        item = _mapping(raw, f"五行.{label}[{index}]")
        if set(item) != {"来源", "目标"}:
            raise ValueError(f"五行.{label}[{index}]字段不完整")
        pairs.add((str(item["来源"]), str(item["目标"])))
    if len(pairs) != 5:
        raise ValueError(f"五行.{label}不能重复")


def _validate_formation_node_rules(value: FormationNodeRules) -> None:
    if (
        not value.enemy_formation_first
        or value.target_count_field != "节点"
        or value.target_sort != ("参战位序",)
        or value.impact_distribution != "均分"
        or not value.unique_targets
        or value.minimum_targets < 1
    ):
        raise ValueError("阵法节点运行契约不受战斗核心支持")


def _validate_neutral_environment_node(value: Any, path: str) -> None:
    forbidden_scopes = {"自身", "己方", "敌方", "关联对象", "主人", "控制者"}
    forbidden_sources = {"自身属性", "效果来源属性"}

    def visit(current: Any, current_path: str) -> None:
        if isinstance(current, Mapping):
            if (
                current.get("能力") == "选择目标"
                and current.get("范围") in forbidden_scopes
            ):
                raise ValueError(f"{current_path}使用了有阵营归属的环境目标")
            if current.get("能力") == "读取数值":
                source = str(current.get("来源") or "")
                if source in forbidden_sources or source.startswith(
                    ("自身当前", "自身已损失")
                ):
                    raise ValueError(f"{current_path}读取了中立环境不存在的自身数值")
            for key, nested in current.items():
                visit(nested, f"{current_path}.{key}")
        elif isinstance(current, list):
            for index, nested in enumerate(current):
                visit(nested, f"{current_path}[{index}]")

    visit(value, path)


def _validate_environment_rules(
    value: Mapping[str, Any],
    events: Mapping[str, Any],
) -> None:
    expected = {
        "秘境默认环境",
        "地表环境来源",
        "承载基准",
        "承伤事件",
        "承伤数值",
        "排除来源身份",
        "阶段方式",
    }
    if set(value) != expected:
        raise ValueError("环境规则字段必须完整且不能包含额外字段")
    if value.get("地表环境来源") != {
        "数据集": "地形分区",
        "坐标字段": "坐标带",
        "环境字段": "地形",
    }:
        raise ValueError("当前地表环境必须由独立地形分区数据集按坐标确定")
    if value.get("承载基准") != ["血气上限"]:
        raise ValueError("战场环境承载基准只能使用正式参战者血气上限")
    event = str(value.get("承伤事件") or "")
    fact = str(value.get("承伤数值") or "")
    event_definition = _mapping(events.get(event), f"环境规则.承伤事件.{event}")
    if fact not in event_definition.get("携带事实", ()):
        raise ValueError("环境规则引用的承伤事件没有携带承伤数值")
    if value.get("排除来源身份") != ["战场环境"]:
        raise ValueError("环境伤害必须排除战场环境自身")
    if value.get("阶段方式") != "替换":
        raise ValueError("战场环境阶段必须使用替换制")


def _validate_action_rules(
    value: Mapping[str, Any],
    attributes: Mapping[str, Any],
    resources: Mapping[str, Any],
) -> None:
    """资源定义必须声明执行器要用到的那几个字段。

    执行器不再认资源名（曾经是 `if 资源 == "血气"` 三分支），一切走 `资源.json` 的
    声明。所以字段缺了不会「静默走默认分支」，而是直接在这里拦下——加第四个资源
    只要照抄这几个字段，不必改代码。

    `加成属性` 允许留空：它是**基准属性**（`治疗效果` / `护盾强度`），默认 100 即
    ×1.0。`精神` 刻意不设——精神是出手预算，把它一起闸掉会让「治疗太强」表现成
    「技能放不出来」，那是另一个问题。留空表示这个资源不做基准缩放。
    """

    required = ("上限属性", "恢复前事件", "恢复后事件", "卡牌加成属性", "受疗加成属性")
    for resource_name, raw in resources.items():
        entry = _mapping(raw, f"资源.{resource_name}")
        absent = [field for field in required if not str(entry.get(field) or "").strip()]
        if absent:
            raise ValueError(f"资源.{resource_name}缺少字段：{'、'.join(absent)}")
        if str(entry["上限属性"]) not in attributes:
            raise ValueError(f"资源.{resource_name}.上限属性引用未知属性：{entry['上限属性']}")
        # 可选字段：写了就必须引用已登记属性；留空表示不参与那一层。
        for field in ("加成属性", "卡牌加成属性", "受疗加成属性"):
            referenced = str(entry.get(field) or "")
            if referenced and referenced not in attributes:
                raise ValueError(f"资源.{resource_name}.{field}引用未知属性：{referenced}")

    expected = {
        "标准速度",
        "最低有效速度",
        "最高行动效率",
        "技能冷却",
        "每次主行动最多追加攻击",
        "事件链深度上限",
        "能力链深度上限",
        "触发技能嵌套上限",
        "每方召唤物上限",
        "战斗构造物上限",
        "行动开始恢复",
        "主动技能轮转",
        "被动技能结算",
    }
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown or missing:
        details = []
        if unknown:
            details.append("未知字段 " + "、".join(sorted(unknown)))
        if missing:
            details.append("缺少字段 " + "、".join(sorted(missing)))
        raise ValueError("行动规则" + "；".join(details))
    for name in ("标准速度", "最低有效速度", "最高行动效率"):
        _positive_number(value[name], f"行动规则.{name}")
    for name in (
        "每次主行动最多追加攻击",
        "事件链深度上限",
        "能力链深度上限",
        "触发技能嵌套上限",
        "每方召唤物上限",
        "战斗构造物上限",
    ):
        if (
            isinstance(value[name], bool)
            or not isinstance(value[name], int)
            or value[name] <= 0
        ):
            raise ValueError(f"行动规则.{name}必须是正整数")
    cooldown = _mapping(value["技能冷却"], "行动规则.技能冷却")
    if set(cooldown) != {"计量单位", "推进", "余数处理"}:
        raise ValueError("行动规则.技能冷却字段必须完整")
    advance = _mapping(cooldown["推进"], "行动规则.技能冷却.推进")
    if (
        cooldown["计量单位"] != "自身行动"
        or advance != {"事件": "行动开始", "阶段": "技能选择前", "每次减少": 1}
        or cooldown["余数处理"] != "向上取整"
    ):
        raise ValueError("行动规则.技能冷却必须明确使用自身行动推进")
    rotation = _mapping(value["主动技能轮转"], "行动规则.主动技能轮转")
    if set(rotation) != {"排序", "游标"}:
        raise ValueError("行动规则.主动技能轮转必须明确同序技能的稳定轮转方式")
    rotation_order = _strings(rotation["排序"], "行动规则.主动技能轮转.排序")
    if (
        set(rotation_order) != {"释放顺序", "装配位序", "物品编号", "能力序号"}
        or len(rotation_order) != 4
    ):
        raise ValueError("行动规则.主动技能轮转.排序必须完整且不可重复")
    cursor = _mapping(rotation["游标"], "行动规则.主动技能轮转.游标")
    if cursor != {"查找方式": "循环正序", "成功后偏移": 1, "无可用行动": "普通攻击"}:
        raise ValueError("行动规则.主动技能轮转包含核心无法执行的方式")
    passive_order = _mapping(value["被动技能结算"], "行动规则.被动技能结算")
    if set(passive_order) != {"排序"}:
        raise ValueError("行动规则.被动技能结算必须明确同序监听的稳定裁决顺序")
    passive_fields = _strings(passive_order["排序"], "行动规则.被动技能结算.排序")
    if (
        set(passive_fields)
        != {
            "监听优先级降序",
            "结算顺序升序",
            "参战位序",
            "装配位序",
            "物品编号",
            "能力序号",
        }
        or len(passive_fields) != 6
    ):
        raise ValueError("行动规则.被动技能结算.排序必须完整且不可重复")
    recovery = _mapping(value["行动开始恢复"], "行动规则.行动开始恢复")
    for resource, attribute in recovery.items():
        if resource not in resources:
            raise ValueError(f"行动规则.行动开始恢复引用未知资源：{resource}")
        if attribute not in attributes:
            raise ValueError(f"行动规则.行动开始恢复引用未知属性：{attribute}")


def _validate_timing(value: Mapping[str, Any]) -> None:
    expected = {"来源层级", "主动技能", "事件监听", "阵法轮转"}
    if set(value) != expected:
        raise ValueError("时序字段必须完整且不能包含额外字段")
    layers = value["来源层级"]
    if not isinstance(layers, list) or not layers:
        raise TypeError("时序.来源层级必须是非空数组")
    seen_sources: set[str] = set()
    seen_orders: set[int] = set()
    for index, raw in enumerate(layers):
        entry = _mapping(raw, f"时序.来源层级[{index}]")
        if set(entry) != {"来源", "序位"}:
            raise ValueError(f"时序.来源层级[{index}]字段必须是来源和序位")
        source = str(entry.get("来源") or "").strip()
        order = entry.get("序位")
        if not source or source in seen_sources:
            raise ValueError("时序来源层级的来源不能为空且不可重复")
        if (
            isinstance(order, bool)
            or not isinstance(order, int)
            or order < 0
            or order in seen_orders
        ):
            raise ValueError("时序来源层级的序位必须是非负且不可重复的整数")
        seen_sources.add(source)
        seen_orders.add(order)
    active = _mapping(value["主动技能"], "时序.主动技能")
    if set(active) != {"执行时点", "排序"}:
        raise ValueError("时序.主动技能字段必须完整")
    if active["执行时点"] != {"事件": "行动决策后", "阶段": "事件完成后"}:
        raise ValueError("主动技能必须在行动决策完成后执行")
    active_order = _strings(active["排序"], "时序.主动技能.排序")
    if (
        set(active_order)
        != {"释放顺序", "来源层级升序", "装配位序", "物品编号", "能力序号"}
        or len(active_order) != 5
    ):
        raise ValueError("时序.主动技能.排序必须完整且不可重复")
    listener = _mapping(value["事件监听"], "时序.事件监听")
    listener_expected = {"执行时点", "排序", "监听快照", "新增监听", "递归", "事件转化"}
    if set(listener) != listener_expected:
        raise ValueError("时序.事件监听字段必须完整")
    if listener["执行时点"] != {"阶段": "事件创建后", "截止": "事件事实提交前"}:
        raise ValueError("事件监听必须在事实提交前执行")
    if listener["监听快照"] != {"固定": True, "时点": "事件创建"}:
        raise ValueError("事件监听必须使用事件创建时的固定快照")
    if listener["新增监听"] != {"生效延迟事件数": 1}:
        raise ValueError("新增监听必须从下一个事件开始生效")
    if listener["递归"] != {"同一监听": "跳过"}:
        raise ValueError("同一监听在当前触发链中必须跳过递归")
    if listener["事件转化"] != {"原事件提交后": True, "新事件链": True}:
        raise ValueError("事件转化必须在原事件提交后开启新事件链")
    listener_order = _strings(listener["排序"], "时序.事件监听.排序")
    if listener_order != EVENT_LISTENER_SORT_ORDER:
        raise ValueError(
            "时序.事件监听.排序必须与战斗核心拼排序键的先后逐字一致"
            f"（期望 {' -> '.join(EVENT_LISTENER_SORT_ORDER)}，实为 {' -> '.join(listener_order)}）；"
            "加减字段时改 `foundation.EVENT_LISTENER_SORT_ORDER`，`mechanics.py` 的键布局要跟着改"
        )
    formation = _mapping(value["阵法轮转"], "时序.阵法轮转")
    if set(formation) != {"执行时点", "双方结算", "冲击判定", "排序", "基准周期"}:
        raise ValueError("时序.阵法轮转字段必须完整")
    # 基准周期是各品级阵法的轮转基准，再由 `传导` 与阶段倍率缩放；
    # 原先写死在 engine.py 里，放进数据后成为可调闸。
    _positive_int(formation["基准周期"], "时序.阵法轮转.基准周期")
    if formation["执行时点"] != {"事件": "行动结束", "阶段": "事件完成后"}:
        raise ValueError("阵法必须在行动结束事件完成后轮转")
    if formation["双方结算"] != {"读取快照": "同一战场", "提交方式": "同时"}:
        raise ValueError("双方阵法必须读取同一战场快照后同时提交")
    if formation["冲击判定"] != {
        "跳过": ["暴击", "命中", "闪避", "格挡", "防御", "环境承伤"]
    }:
        raise ValueError("阵法冲击判定规则不受战斗核心支持")
    formation_order = _strings(formation["排序"], "时序.阵法轮转.排序")
    if formation_order != ("方位序位", "阵法编号"):
        raise ValueError("时序.阵法轮转.排序必须使用方位序位、阵法编号")


def _validate_damage_rules(value: Mapping[str, Any]) -> None:
    expected = {
        "基础命中率",
        "最低命中率",
        "最高命中率",
        "最高暴击倍率",
        "最高格挡率",
        "最高伤害倍率",
        "防御常数",
        "最低伤害",
        "输出倍率",
        "最高伤害减免",
    }
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown or missing:
        raise ValueError(
            "伤害规则字段不完整："
            + ("未知 " + "、".join(sorted(unknown)) if unknown else "")
            + ("；" if unknown and missing else "")
            + ("缺少 " + "、".join(sorted(missing)) if missing else "")
        )
    for name, number in value.items():
        _positive_number(number, f"伤害规则.{name}", allow_zero=name != "防御常数")
    if not value["最低命中率"] <= value["基础命中率"] <= value["最高命中率"]:
        raise ValueError("伤害规则命中率必须满足最低值 <= 基础值 <= 最高值")


def _validate_status_reactions(value: Any, validator: RuleSchemaValidator) -> None:
    if not isinstance(value, list):
        raise TypeError("状态反应必须是数组")
    names: set[str] = set()
    for index, raw in enumerate(value):
        reaction = _mapping(raw, f"状态反应[{index}]")
        unknown = set(reaction) - {"名称", "需要状态", "消耗层数", "生成状态", "效果"}
        if unknown:
            raise ValueError(
                f"状态反应[{index}]存在未知字段：{'、'.join(sorted(unknown))}"
            )
        name = str(reaction.get("名称") or "").strip()
        if not name or name in names:
            raise ValueError(f"状态反应[{index}].名称必须非空且不可重复")
        names.add(name)
        required = _strings(reaction.get("需要状态"), f"状态反应[{index}].需要状态")
        if len(required) < 2 or len(required) != len(set(required)):
            raise ValueError(f"状态反应[{index}].需要状态至少两项且不可重复")
        consume = reaction.get("消耗层数", 1)
        if isinstance(consume, bool) or not isinstance(consume, int) or consume < 0:
            raise ValueError(f"状态反应[{index}].消耗层数必须是非负整数")
        generated = reaction.get("生成状态")
        if generated is not None:
            status = _mapping(generated, f"状态反应[{index}].生成状态")
            if not str(status.get("名称") or "").strip():
                raise ValueError(f"状态反应[{index}].生成状态必须有名称")
            validator.validate_node(
                {
                    "能力": "添加状态",
                    "目标": {"能力": "选择目标", "范围": "自身"},
                    "状态": dict(status),
                },
                f"状态反应[{index}].生成状态",
            )
        effects = reaction.get("效果", [])
        if not isinstance(effects, list):
            raise TypeError(f"状态反应[{index}].效果必须是数组")
        for effect_index, effect in enumerate(effects):
            validator.validate_node(effect, f"状态反应[{index}].效果[{effect_index}]")


def _positive_number(value: Any, path: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{path}必须是数字")
    result = float(value)
    if result < 0 or (result == 0 and not allow_zero):
        raise ValueError(f"{path}必须{'非负' if allow_zero else '大于零'}")
    return result


def _positive_int(value: Any, path: str) -> int:
    """正整数校验。`bool` 是 `int` 的子类，必须显式排除。"""

    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{path}必须是整数")
    if value <= 0:
        raise ValueError(f"{path}必须大于零")
    return value


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{path}必须是对象")
    return value


def _strings(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ValueError(f"{path}必须是非空字符串数组")
    return tuple(value)
