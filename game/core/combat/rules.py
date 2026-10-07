"""战斗规则层：**锁定技**（名字用我们的，机制用游戏王的效果外文本），全部由数据写。

**名字与机制分开说清楚。** 这类文本我们叫它**锁定技**（设计侧与卡面口径都这么叫）；它的
**机制**照游戏王的「效果外文本」实现，判据只有一条——**它不是效果**：

1. **不进效果管线**：不产生事件、没有触发点、不进连锁——所以「效果无效 / 取消 / 转化 /
   改数值」这一类改写**根本够不着它**（不是"免疫"，是"不在射程内"）；
2. **由规则读它做合法性判定**：能不能被选为目标、能不能被改、能不能被禁——像召唤条件与
   属性那样，是卡片的结构性文字，不是「发生了什么」；
3. **它不「发动」**：没有发动时点，所以「必发 / 可选」这一维对它不成立。

**不采用三国杀那个「必须发动」的语义。** 必发在这个引擎里是**默认底色**（全部被动、环境
常驻、阵法都必发，没有一处能写「可以不发动」），拿它当判据等于没有判据。

所以「改不掉」也不等于锁定技：一个效果改不掉，可能只是**暂时没有能改它的东西**（气机的
属性加成、形态的属性变化、战场环境的常驻能力都是这一类）。要一个效果真的改不掉，正确做法
是**给它挂一条锁定技**，而不是指望别人没有对应的能力。

## 一条规则 = 一个拦截点 + 一组条件 + 一个处置

规则的形状与卡片同构：**条件用已登记的条件原子写**（`标签条件` / `组合条件` /
`数值条件`…），**处置只有两种**（`拒绝` / `允许`），参数以 `$字段` 写进条件里，
装载期替换成卡片声明的取值。于是：

- 加一条**落在已有拦截点**上的规则 = **只写 `规则层.json` 一行**（加卡面文案），
  不改代码、不加判据——与「加一张功法」同一档成本；
- 只有**新增一种拦截点**才要写代码，而那相当于新增一个原子能力（新的原语），
  引擎里那处判定是唯一该改的地方。

**条件不许为空，两种载体一视同仁**：一条没有条件的规则拦的是那一处的**全部**请求，
而卡面写的总比这窄——`不可禁用` 第一版就是这样顺带把改冷却、改名称也拦了的。
启动期与 `tools/架构审查/检查规则层.py` 共用同一份校验，所以这种规则进不来。

## 拦截点决定规则能挂在哪儿

**载体**是规则写在哪：`单位` 写在卡面根能力 `规则文本` 的 `规则[]` 里（跟参战者上战场），
`行` 写在能力行自己的 `规则[]` 里（跟着那一行走，例如「这一条主动技能不可被禁用」）。
每个拦截点只认它读得到的载体，登记表写错载体当场报错。

## 拦截点把请求写成标签，条件直接匹配

引擎侧的拦截点会把「这次请求」编码成标签（`来源关系:敌方`、`方式:增加`、`字段:禁用`、
`改写:取消`…），条件用现成的 `标签条件` 匹配——所以**不需要为规则新增任何条件词汇**。
参数以 `$字段` 写进标签：`"来源关系:$来源"` + 参数 `敌方` → `来源关系:敌方`；
参数留空（`允许空`）时**含它的那条条件整条丢掉**，语义是「这一项不设限」。

## 优先级与可改写

`优先级` 决定同一拦截点上多条规则的先后（升序）；`可改写` 默认空 = 不可被任何规则改写，
要允许某条规则覆盖它就在 `可改写` 里列出那条规则名。两条都**真的有语义**：拦截点按优先级
依次问，后问的规则只有在先成立的那条允许被它改写时，才能改变结论。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

#: 单位级规则的载体：卡面根能力名与它装规则的字段名。
RULE_TEXT_ABILITY = "规则文本"
#: 规则数组的字段名——单位级与行级同名同形。
RULE_FIELD = "规则"
#: 行级规则的载体能力：只有这些行会被引擎按行问规则。
#: **加一种行级载体 = 在这里加一个名字**，同时那处装配要问一次 `_line_rules`。
#: 登记行级规则时会核对这里的能力真的声明了 `规则` 字段，脱钩当场报错。
RULE_LINE_ABILITIES = ("主动技能",)
#: 参数占位前缀：条件里写 `$来源`，装载期替换成卡片声明的取值。
PLACEHOLDER = "$"

#: 处置：拒绝这次改写/选定，或允许（`允许` 用来写「某条规则可以被它覆盖」）。
RULE_DISPOSITIONS = frozenset({"拒绝", "允许"})

#: 单位级规则的参数类型，只允许这几种（都能直接印进卡面或标签）。
RULE_VALUE_TYPES = frozenset({"字符串", "字符串数组", "布尔", "整数", "数字"})


@dataclass(frozen=True)
class InterceptionPoint:
    """一个拦截点：说明 + 认哪些载体 + 标准探针会生成的请求标签。"""

    note: str
    carriers: tuple[str, ...]
    #: 登记一条规则时，它的条件所匹配的标签必须落在这里面；落不进去就说明
    #: 「加规则自动获得行为验证」不成立，判据会要求作者扩展探针场景。
    probe_tags: tuple[str, ...]


#: 代码侧权威表：新增拦截点 = 在这里登记 + 在引擎那处判定里调用 `_rules_deny`。
INTERCEPTION_POINTS = MappingProxyType(
    {
        "被选为目标": InterceptionPoint(
            note="效果逐候选挑目标时问候选自己",
            carriers=("单位",),
            #: 三个方向都造得出来：敌方打过来、同伴给你加、你自己给自己加。
            probe_tags=("来源关系:敌方", "来源关系:己方", "来源关系:自身"),
        ),
        "行动条被改写": InterceptionPoint(
            note="修改行动条落到某个单位时问被改写的单位",
            carriers=("单位",),
            probe_tags=(
                "来源关系:敌方",
                "来源关系:己方",
                "来源关系:自身",
                "方式:增加",
            ),
        ),
        "事件被改写": InterceptionPoint(
            note="取消 / 转化 / 改数值时问事件的承受者",
            carriers=("单位",),
            #: 标准探针现在能造出这三种改写；要加 改写:目标 / 改写:标签 这类规则，
            #: 先扩 tools/行为验证/验证规则层.py 的对应场景，再把标签加到这里（判据会要求）。
            probe_tags=("改写:取消", "改写:转化", "改写:数值"),
        ),
        "技能被改写": InterceptionPoint(
            note="修改技能落到某个技能时问那个技能自己",
            carriers=("行",),
            #: 标准探针会造三种改写：禁用（`字段:禁用` + `值:真`）与冷却延长（`字段:冷却行动`
            #: + `方式:增加`）；再加一种就先把 `tools/行为验证/验证规则层.py` 的对应场景补上。
            probe_tags=("字段:禁用", "值:真", "字段:冷却行动", "方式:增加"),
        ),
        "状态被添加": InterceptionPoint(
            note="给别人挂状态之前问**被打上的那个单位**",
            carriers=("单位",),
            #: 请求摊成四类标签：具体状态名、类别、是不是控制、来源关系。
            #: 于是「不受控制」「不吃负面状态」「只不受某一条」都能用现成的条件原子写。
            probe_tags=(
                "状态:探针封",
                "类别:负面",
                "类别:正面",
                "控制:真",
                "来源关系:敌方",
                "来源关系:己方",
                "来源关系:自身",
            ),
        ),
        "资源被消耗": InterceptionPoint(
            note="扣某个单位的资源之前问那个单位",
            carriers=("单位",),
            probe_tags=(
                "方式:消耗",
                "资源:精神",
                "资源:血气",
                "来源关系:敌方",
                "来源关系:己方",
                "来源关系:自身",
            ),
        ),
        "行动被限制": InterceptionPoint(
            note="一条状态要限制某次行动时，问被限制的那个单位",
            carriers=("单位",),
            probe_tags=(
                "限制:行动",
                "限制:技能",
                "来源关系:敌方",
                "来源关系:己方",
                "来源关系:自身",
            ),
        ),
        "归属被修改": InterceptionPoint(
            note="改阵营 / 主人 / 控制者之前问被改的那个单位",
            carriers=("单位",),
            probe_tags=(
                "字段:阵营",
                "来源关系:敌方",
                "来源关系:己方",
                "来源关系:自身",
            ),
        ),
        "形态被切换": InterceptionPoint(
            note="切某个单位的形态之前问那个单位",
            carriers=("单位",),
            probe_tags=(
                "形态:探针形态",
                "来源关系:敌方",
                "来源关系:己方",
                "来源关系:自身",
            ),
        ),
        "计量被修改": InterceptionPoint(
            note="动某个单位的构筑计量之前问那个单位",
            carriers=("单位",),
            probe_tags=(
                "计量:探针计量",
                "方式:增加",
                "来源关系:敌方",
                "来源关系:己方",
                "来源关系:自身",
            ),
        ),
        "状态被移除": InterceptionPoint(
            note="清掉 / 吃掉 / 到期收走某个状态之前问挂着它的那个单位",
            carriers=("单位",),
            probe_tags=(
                "状态:探针封",
                "类别:负面",
                "原因:清除",
                "原因:消耗",
                "原因:到期",
                "原因:来源退场",
                "来源关系:敌方",
                "来源关系:己方",
                "来源关系:自身",
            ),
        ),
        "造物被召唤": InterceptionPoint(
            note="要造出一个战斗对象（召唤物 / 构造物）之前问**召唤者自己**",
            carriers=("单位",),
            probe_tags=("类型:参战者", "类型:构造物", "来源关系:自身"),
        ),
    }
)


def spec_allows_empty(spec: Mapping[str, Any]) -> bool:
    """这个参数留空算不算合法（`允许空`，或者根本没给它默认值）。"""

    return bool(spec.get("允许空")) or spec.get("默认") in (None, "")


def _placeholder_names(value: Any) -> set[str]:
    """收集条件里出现的 `$字段` 名。"""

    found: set[str] = set()
    if isinstance(value, str):
        if value.startswith(PLACEHOLDER) and len(value) > 1:
            found.add(value[1:])
        elif PLACEHOLDER in value:
            _, _, tail = value.partition(PLACEHOLDER)
            if tail:
                found.add(tail)
    elif isinstance(value, Mapping):
        for item in value.values():
            found |= _placeholder_names(item)
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for item in value:
            found |= _placeholder_names(item)
    return found


def _substitute(value: Any, params: Mapping[str, Any]) -> Any:
    """把 `$字段` 替换成参数取值；整串只由参数组成时保留原值类型。"""

    if isinstance(value, str):
        if len(value) > 1 and value == PLACEHOLDER + value[1:] and value[1:] in params:
            return params[value[1:]]
        text = value
        for name, item in params.items():
            text = text.replace(PLACEHOLDER + name, str(item))
        return text
    if isinstance(value, Mapping):
        return {key: _substitute(item, params) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [_substitute(item, params) for item in value]
    return value


def expand_rule(
    name: str,
    params: Mapping[str, Any],
    layer: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """把「规则名 + 参数」展开成引擎可直接问的一条规则。

    参数留空时，**含该占位符的那条条件整条丢掉**——所以「来源不限」不需要另写一条规则。
    """

    definition = dict(layer.get(name) or {})
    if not definition:
        raise ValueError(f"规则层没有登记这条规则：{name}")
    declarations = dict(definition.get("字段") or {})
    filled = {
        field: params.get(field, spec.get("默认"))
        for field, spec in declarations.items()
    }
    conditions: list[Any] = []
    for raw in definition.get("条件") or ():
        used = _placeholder_names(raw)
        if any(filled.get(item) in (None, "") for item in used):
            continue
        conditions.append(_substitute(dict(raw), filled))
    return {
        "名称": name,
        "拦截点": str(definition.get("拦截点") or ""),
        "处置": str(definition.get("处置") or ""),
        "优先级": int(definition.get("优先级") or 0),
        "可改写": tuple(str(item) for item in definition.get("可改写") or ()),
        "条件": conditions,
        "参数": filled,
    }


def validate_rule_layer(
    value: Mapping[str, Any],
    abilities: Mapping[str, Any],
    validator: Any,
) -> dict[str, dict]:
    """校验登记表本身（启动期与判据共用同一份）。

    除了归属/拦截点/处置/优先级/名额/可改写/卡面这些结构，**条件也真的校验**：每条条件按
    原子能力的契约走一遍（未登记的条件、越界字段当场报错），参数必须写在 `字段` 里、且每个
    字段至少被一条条件用到——死参数与死条件都不许留。
    """

    if not isinstance(value, Mapping):
        raise TypeError("战斗定义.规则层必须是对象")
    layer: dict[str, dict] = {}
    priorities: dict[int, str] = {}
    for raw_name, raw in value.items():
        name = str(raw_name or "").strip()
        if not name:
            raise ValueError("规则层存在空规则名")
        if not isinstance(raw, Mapping):
            raise TypeError(f"规则层.{name}必须是对象")
        definition = dict(raw)
        carrier = str(definition.get("归属") or "")
        point_name = str(definition.get("拦截点") or "")
        point = INTERCEPTION_POINTS.get(point_name)
        if point is None:
            raise ValueError(
                f"规则层.{name}的拦截点没有实现：{point_name or '<空>'}；"
                "可用：" + "、".join(INTERCEPTION_POINTS)
            )
        if carrier not in point.carriers:
            raise ValueError(
                f"规则层.{name}：拦截点 {point_name} 只认载体 {'、'.join(point.carriers)}，"
                f"登记写 {carrier or '<空>'}"
            )
        disposition = str(definition.get("处置") or "")
        if disposition not in RULE_DISPOSITIONS:
            raise ValueError(f"规则层.{name}.处置只能是：{'、'.join(sorted(RULE_DISPOSITIONS))}")
        priority = definition.get("优先级")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise ValueError(f"规则层.{name}.优先级必须是整数")
        if priority in priorities:
            raise ValueError(f"规则层优先级重复：{name} 与 {priorities[priority]} 都是 {priority}")
        priorities[priority] = name
        # 名额：**这一条锁定技全库最多能让几张卡带**。它不是稀有度崇拜（锁定技不是靠稀有
        # 保值的），而是防一条闸门被抄到所有卡上（二十张卡都「不可被指定」，选目标这件事
        # 本身就没意义了）。默认 1：想多发一张，先在登记表里抬这个数——一次显式的设计决定。
        quota = definition.get("名额")
        if isinstance(quota, bool) or not isinstance(quota, int) or quota < 1:
            raise ValueError(f"规则层.{name}.名额必须是正整数（至少 1）")
        # 种族名额：**种族是天生层，与卡是两本账**——卡的闸门不被种族撑宽，种族的发行量
        # 单独一个数。只有单位级规则带它（种族只能用单位级规则），不写就与卡同额。
        if "种族名额" in definition and carrier != "单位":
            raise ValueError(
                f"规则层.{name}：{carrier}级规则不给种族用，不要写种族名额"
            )
        race_quota = definition.get("种族名额", quota)
        if isinstance(race_quota, bool) or not isinstance(race_quota, int) or race_quota < 1:
            raise ValueError(f"规则层.{name}.种族名额必须是正整数（至少 1）")
        if not str(definition.get("卡面") or "").strip():
            raise ValueError(f"规则层.{name}缺少卡面文案（规则文本由数据渲染，不许手写）")
        rewrite = definition.get("可改写") or ()
        if not isinstance(rewrite, Sequence) or isinstance(rewrite, str):
            raise TypeError(f"规则层.{name}.可改写必须是数组")
        for target in rewrite:
            if str(target) not in value:
                raise ValueError(f"规则层.{name}.可改写指向未登记的规则：{target}")
            if str(target) == name:
                raise ValueError(f"规则层.{name}不能改写自己")
        fields = definition.get("字段") or {}
        if not isinstance(fields, Mapping):
            raise TypeError(f"规则层.{name}.字段必须是对象")
        for field, spec in fields.items():
            if not isinstance(spec, Mapping):
                raise TypeError(f"规则层.{name}.字段.{field}必须是对象")
            kind = str(spec.get("类型") or "")
            if kind not in RULE_VALUE_TYPES:
                raise ValueError(f"规则层.{name}.字段.{field}的类型不认识：{kind or '<空>'}")

        conditions = definition.get("条件") or ()
        if carrier == "行":
            carriers = [
                ability
                for ability in RULE_LINE_ABILITIES
                if RULE_FIELD in dict(dict(abilities.get(ability) or {}).get("字段") or {})
            ]
            if not carriers:
                raise ValueError(
                    f"规则层.{name}是行级规则，但行级载体的能力"
                    f"（{'、'.join(RULE_LINE_ABILITIES)}）没有声明 {RULE_FIELD} 字段"
                )
        # 条件对两种载体一视同仁：**一条没有条件的规则会把这一处的所有请求都拦掉**，
        # 而卡面写的一定比这窄（曾经 `不可禁用` 就是这样把改冷却、改名称一起拦了的）。
        if not isinstance(conditions, Sequence) or isinstance(conditions, str) or not conditions:
            raise ValueError(f"规则层.{name}至少要写一条条件（否则它拦的是这一处全部请求）")
        used_fields: set[str] = set()
        for index, node in enumerate(conditions):
            where = f"规则层.{name}.条件[{index}]"
            if not isinstance(node, Mapping):
                raise TypeError(f"{where}必须是对象")
            validator.validate_node(node, where, allowed_categories=("条件",))
            used_fields |= _placeholder_names(node)
            # **可空参数的占位符不许跟固定标签写在同一条条件里**：参数留空时整条条件会被
            # 丢掉（那是「这一项不设限」的写法），固定标签会被一起吞掉，规则就变成无条件
            # 拦截。实测踩过：`不受控制` 的条件写成 `[控制:真, 来源关系:$来源]`，卡里不写
            # 来源（= 不限来源）时整条被丢，于是它拦掉了**所有**状态，连自己挂的状态都挂不上。
            empty_able = {
                field
                for field in _placeholder_names(node)
                if spec_allows_empty(dict(fields).get(field) or {})
            }
            fixed_labels = [
                str(label)
                for label in dict(node).get("标签") or ()
                if PLACEHOLDER not in str(label)
            ]
            if empty_able and fixed_labels:
                raise ValueError(
                    f"{where}把可空参数（{'、'.join(sorted(empty_able))}）与固定标签"
                    f"（{'、'.join(fixed_labels)}）写在同一条件里：参数留空会把固定标签一起丢掉，"
                    "拆成两条条件"
                )
        unknown = used_fields - set(fields)
        if unknown:
            raise ValueError(f"规则层.{name}的条件引用了未声明参数：{'、'.join(sorted(unknown))}")
        dead = set(fields) - used_fields
        if dead:
            raise ValueError(f"规则层.{name}声明了没有任何条件使用的参数：{'、'.join(sorted(dead))}")
        layer[name] = definition
    return layer


def parse_rule_entries(
    entries: Any,
    layer: Mapping[str, Mapping[str, Any]],
    *,
    carrier: str,
    path: str,
) -> dict[str, dict]:
    """解析一处 `规则[]`（单位级或行级），返回 `规则名 -> 展开后的规则`。"""

    if entries is None:
        return {}
    if not isinstance(entries, Sequence) or isinstance(entries, str | bytes):
        raise TypeError(f"{path}必须是数组")
    result: dict[str, dict] = {}
    for index, raw in enumerate(entries):
        where = f"{path}[{index}]"
        if not isinstance(raw, Mapping):
            raise TypeError(f"{where}必须是对象")
        entry = dict(raw)
        name = str(entry.pop("名称", "") or "").strip()
        definition = layer.get(name)
        if definition is None:
            raise ValueError(f"{where}.名称不是登记的规则：{name or '<空>'}")
        if str(definition.get("归属")) != carrier:
            raise ValueError(
                f"{where}.名称是{definition.get('归属')}级规则，不能写在{carrier}里：{name}"
            )
        if name in result:
            raise ValueError(f"{where}重复声明了同一条规则：{name}")
        declared = dict(definition.get("字段") or {})
        unknown = set(entry) - set(declared)
        if unknown:
            raise ValueError(
                f"{where}存在未声明参数：{'、'.join(sorted(str(item) for item in unknown))}"
            )
        params: dict[str, Any] = {}
        for field, spec in declared.items():
            value = entry.get(field, spec.get("默认"))
            if value in (None, ""):
                if spec.get("必填") and not spec.get("允许空"):
                    raise ValueError(f"{where}.{field}是必填参数")
                params[field] = ""
                continue
            options = spec.get("选项")
            if options and value not in options:
                raise ValueError(
                    f"{where}.{field}只能是：{'、'.join(str(item) for item in options)}（留空表示不设限）"
                )
            params[field] = value
        result[name] = expand_rule(name, params, layer)
    return result


def probe_tags(rule: Mapping[str, Any]) -> set[str]:
    """这条规则在标准探针里需要的请求标签（把条件里的标签字面量全取出来）。"""

    tags: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            for item in value.values():
                collect(item)
        elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
            for item in value:
                collect(item)
        elif isinstance(value, str) and PLACEHOLDER not in value and ":" in value:
            tags.add(value)

    for condition in rule.get("条件") or ():
        for label in dict(condition).get("标签") or ():
            collect(label)
    return tags


def rule_card_text(
    name: str,
    params: Mapping[str, Any],
    layer: Mapping[str, Mapping[str, Any]],
) -> str:
    """按登记表的卡面文案拼一句话；占位符取自参数，留空印「不限」。"""

    definition = layer.get(name) or {}
    template = str(definition.get("卡面") or name)
    text = template
    for field, spec in dict(definition.get("字段") or {}).items():
        value = params.get(field, spec.get("默认"))
        shown = "不限" if value in (None, "") else str(value)
        text = text.replace("{" + str(field) + "}", shown)
    return text


__all__ = [
    "INTERCEPTION_POINTS",
    "PLACEHOLDER",
    "RULE_DISPOSITIONS",
    "RULE_FIELD",
    "RULE_LINE_ABILITIES",
    "RULE_TEXT_ABILITY",
    "RULE_VALUE_TYPES",
    "InterceptionPoint",
    "expand_rule",
    "parse_rule_entries",
    "probe_tags",
    "rule_card_text",
    "validate_rule_layer",
]
