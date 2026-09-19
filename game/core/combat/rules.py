"""战斗规则层：效果之外的常驻规则。

**这一层回答「引擎怎么看这个单位/这一行」，不回答「发生了什么」。** 效果管线负责结算，
规则层负责合法性，所以规则层天然免疫「效果无效」这一类改写——这正是它存在的理由：
三国杀的锁定技与游戏王的效果外文本，本质是同一件事的两种写法（前者说「不许被改写」，
后者说「不属于效果管线」）。

## 两个归属

- `单位`：写在卡面根能力 `规则文本` 的 `规则[]` 里，跟着参战者走到战场。例：不可被指定。
- `行`：写成能力行上的一个字段（必须先在 `原子能力.json` 里声明）。例：主动技能的 `不可禁用`。

两个归属都必须**先登记再使用**：登记表是 `data/战斗/定义/规则层.json`，本模块是它的
代码侧：`RULE_CONSUMERS` 是**消费者 -> 归属**的权威表（判据拿它核对登记表，反向也核）。
登记了却没有消费者的规则**必须报错**——那会变成一条写在卡面上、跑起来什么也不做的规则，
比没有这条规则更坏（第 86 轮的战报教训：键读错了不会报错，只会让人以为单位类型叫「参战者」）。

## 优先级与改写

`优先级` 是规则之间的顺序，必须唯一（冲突时不许靠实现顺序决定结果）。
`可改写` 默认空 = **不可被任何规则改写**；要允许某条规则覆盖它，就在这里列出那条规则名。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

#: 消费者 -> 它所在的归属。加消费者必须同时加登记项，反之亦然（判据双向核对）。
RULE_CONSUMERS = MappingProxyType(
    {
        "目标合法性": "单位",
        "时序提前": "单位",
        "技能封禁": "行",
    }
)

#: 单位级规则的参数类型，只允许这几种（都要能被卡面直接印出来）。
RULE_VALUE_TYPES = frozenset({"字符串", "字符串数组", "布尔", "整数", "数字"})

#: 单位级规则的载体：卡面根能力名与它装规则的字段名。
RULE_TEXT_ABILITY = "规则文本"
RULE_TEXT_FIELD = "规则"


def validate_rule_layer(value: Mapping[str, Any], abilities: Mapping[str, Any]) -> dict[str, dict]:
    """校验登记表本身，返回 `规则名 -> 定义`。

    启动期就拦住的四类错：归属与消费者对不上、优先级重复、可改写指向不存在的规则、
    行级规则的字段没有在 `原子能力.json` 里声明（写了内容也只会「规则不认识字段」）。
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
        owner = str(definition.get("归属") or "")
        consumer = str(definition.get("消费者") or "")
        if owner not in {"单位", "行"}:
            raise ValueError(f"规则层.{name}.归属只能是单位或行")
        if consumer not in RULE_CONSUMERS:
            raise ValueError(f"规则层.{name}的消费者没有实现：{consumer or '<空>'}")
        if RULE_CONSUMERS[consumer] != owner:
            raise ValueError(
                f"规则层.{name}的归属与消费者不一致：{consumer} 属于 {RULE_CONSUMERS[consumer]}"
            )
        priority = definition.get("优先级")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise ValueError(f"规则层.{name}.优先级必须是整数")
        if priority in priorities:
            raise ValueError(f"规则层优先级重复：{name} 与 {priorities[priority]} 都是 {priority}")
        priorities[priority] = name
        if not str(definition.get("卡面") or "").strip():
            raise ValueError(f"规则层.{name}缺少卡面文案（规则文本由数据渲染，不许手写）")
        rewrite = definition.get("可改写") or []
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
        if owner == "行":
            if fields:
                raise ValueError(f"规则层.{name}是行级规则，参数应写在能力行的字段声明里")
            if not any(name in dict(spec.get("字段") or {}) for spec in abilities.values()):
                raise ValueError(
                    f"规则层.{name}是行级规则，但没有任何原子能力声明这个字段"
                )
        else:
            for field, spec in fields.items():
                if not isinstance(spec, Mapping):
                    raise TypeError(f"规则层.{name}.字段.{field}必须是对象")
                kind = str(spec.get("类型") or "")
                if kind not in RULE_VALUE_TYPES:
                    raise ValueError(f"规则层.{name}.字段.{field}的类型不认识：{kind or '<空>'}")
        layer[name] = definition
    return layer


def parse_unit_rules(
    entries: Any,
    layer: Mapping[str, Mapping[str, Any]],
    *,
    path: str,
) -> dict[str, dict]:
    """解析卡面 `规则文本.规则[]`，返回 `规则名 -> 参数`（缺省值已补齐）。"""

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
        if str(definition.get("归属")) != "单位":
            raise ValueError(f"{where}.名称是行级规则，不能写在规则文本里：{name}")
        if name in result:
            raise ValueError(f"{where}重复声明了同一条规则：{name}")
        declared = dict(definition.get("字段") or {})
        unknown = set(entry) - set(declared)
        if unknown:
            raise ValueError(f"{where}存在未声明参数：{'、'.join(sorted(str(item) for item in unknown))}")
        params: dict[str, Any] = {}
        for field, spec in declared.items():
            value = entry.get(field, spec.get("默认"))
            if value is None:
                if spec.get("必填"):
                    raise ValueError(f"{where}.{field}是必填参数")
                continue
            options = spec.get("选项")
            if options and value not in options:
                raise ValueError(
                    f"{where}.{field}只能是：{'、'.join(str(item) for item in options)}"
                )
            params[field] = value
        result[name] = params
    return result


def rule_card_text(
    name: str,
    params: Mapping[str, Any],
    layer: Mapping[str, Mapping[str, Any]],
) -> str:
    """按登记表的卡面文案拼一句话；占位符取自参数（合法参数已在解析时校验）。"""

    definition = layer.get(name) or {}
    template = str(definition.get("卡面") or name)
    text = template
    for field, value in params.items():
        text = text.replace("{" + str(field) + "}", str(value))
    return text


__all__ = [
    "RULE_CONSUMERS",
    "RULE_TEXT_ABILITY",
    "RULE_TEXT_FIELD",
    "RULE_VALUE_TYPES",
    "parse_unit_rules",
    "rule_card_text",
    "validate_rule_layer",
]
