"""将上层构筑的词条定义展开到战斗机制副本。"""
from __future__ import annotations
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

TERM_CATEGORIES = ("计量", "状态", "规则", "判定")
SLOT_KEYS = {"计量槽位": "计量", "状态槽位": "状态", "规则槽位": "规则", "判定槽位": "判定"}

def construct_term_table(definition: Mapping[str, Any]) -> Mapping[str, Any]:
    value = definition.get("词条")
    return value if isinstance(value, Mapping) else {}

def resolve_term(definition: Mapping[str, Any], category: str, slot: str) -> Mapping[str, Any]:
    table = construct_term_table(definition).get(category)
    if not isinstance(table, Mapping) or not isinstance(table.get(slot), Mapping):
        raise KeyError(f"构筑未定义{category}槽位：{slot}")
    return table[slot]

def bind_mechanism_parameters(definition: Mapping[str, Any], parameters: Mapping[str, Any]) -> dict[str, Any]:
    table = construct_term_table(definition)
    result: dict[str, Any] = {}
    for port, slot in parameters.items():
        if not isinstance(port, str) or not port.strip() or not isinstance(slot, str) or not slot.strip():
            raise ValueError(f"机制参数端口无效：{port}")
        category = port.split("_", 1)[0].split(":", 1)[0]
        if category not in TERM_CATEGORIES:
            raise ValueError(f"未知机制参数端口：{port}")
        category_table = table.get(category)
        if not isinstance(category_table, Mapping) or slot not in category_table:
            raise KeyError(f"机制参数未绑定到{category}词条：{slot}")
        result[port] = slot
    return result

def bind_term_slots(definition: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(definition))
    parameters = result.get("机制参数")
    if isinstance(parameters, Mapping):
        result["机制参数"] = bind_mechanism_parameters(result, parameters)
    _bind_value(result, result)
    return result

def _bind_value(value: Any, root: Mapping[str, Any]) -> Any:
    if isinstance(value, list):
        for i, item in enumerate(value): value[i] = _bind_value(item, root)
        return value
    if not isinstance(value, dict): return value
    parameters = root.get("机制参数")
    if isinstance(parameters, Mapping):
        for port, slot in parameters.items():
            if not isinstance(port, str) or not isinstance(slot, str): continue
            category = port.split("_", 1)[0].split(":", 1)[0]
            if category == "计量" and value.get("计量") in {port, port.split(":", 1)[-1]}: value["计量槽位"] = slot
            elif category == "状态" and "状态槽位" not in value: value["状态槽位"] = slot
            elif category == "规则" and "规则槽位" not in value: value["规则槽位"] = slot
            elif category == "判定" and "判定槽位" not in value: value["判定槽位"] = slot
    for key, child in tuple(value.items()): value[key] = _bind_value(child, root)
    for slot_key, category in SLOT_KEYS.items():
        slot = value.get(slot_key)
        if not isinstance(slot, str) or not slot.strip(): continue
        term = dict(resolve_term(root, category, slot.strip()))
        if category == "计量":
            value["计量"] = slot.strip()
            if "上限" in term: value["最高值"] = term["上限"]
            value["计量显示名"] = term.get("显示名", term.get("名称", slot.strip()))
        elif category == "状态":
            current = value.get("状态")
            value["状态"] = {**term, **(current if isinstance(current, dict) else {})}
        elif category == "规则":
            value["名称"] = term.get("显示名", term.get("名称", slot.strip()))
            for key in ("规则", "重复处理", "来源退场时移除"):
                if key in term: value[key] = deepcopy(term[key])
        elif category == "判定":
            value["判定"] = term.get("判定", slot.strip())
            value["方式"] = term.get("方式", "必定成功")
            if "次数" in term: value["次数"] = term["次数"]
    return value

__all__ = ["TERM_CATEGORIES", "SLOT_KEYS", "bind_term_slots", "bind_mechanism_parameters", "construct_term_table", "resolve_term"]
