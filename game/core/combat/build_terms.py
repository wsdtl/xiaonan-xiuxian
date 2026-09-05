"""构筑词条槽位的绑定与校核辅助。

词条名称属于功法、真意、气机或器律；战斗核心只处理槽位和基础操作。
本模块不保存全局词条，也不把一个构筑的定义复制到另一个构筑。
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


TERM_CATEGORIES = ("计量", "状态", "规则", "判定")
SLOT_KEYS = {
    "计量槽位": "计量",
    "状态槽位": "状态",
    "规则槽位": "规则",
    "判定槽位": "判定",
}


def construct_term_table(definition: Mapping[str, Any]) -> Mapping[str, Any]:
    """返回构筑自己的词条表；没有词条表的旧构筑返回空映射。"""

    value = definition.get("词条")
    return value if isinstance(value, Mapping) else {}


def resolve_term(
    definition: Mapping[str, Any], category: str, slot: str
) -> Mapping[str, Any]:
    """解析当前构筑的本地槽位，不允许回退到公共或其他构筑。"""

    table = construct_term_table(definition)
    category_table = table.get(category)
    if not isinstance(category_table, Mapping):
        raise KeyError(f"构筑未定义词条类别：{category}")
    value = category_table.get(slot)
    if not isinstance(value, Mapping):
        raise KeyError(f"构筑未定义{category}槽位：{slot}")
    return value


def bind_term_slots(definition: Mapping[str, Any]) -> dict[str, Any]:
    """将效果中的槽位引用绑定为当前构筑的本地定义。

    绑定只发生在构筑装配副本上。内部计量仍使用槽位名并结合构筑实例隔离，
    状态、规则和判定则读取词条定义中的玩家可见名称与效果字段。
    """

    result = deepcopy(dict(definition))
    _bind_value(result, result)
    return result


def _bind_value(value: Any, root: Mapping[str, Any]) -> Any:
    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = _bind_value(item, root)
        return value
    if not isinstance(value, dict):
        return value

    table = construct_term_table(root)
    # 共享机制仍可使用旧的逻辑名；进入具体构筑后，将它映射到本构筑槽位。
    # 新数据可直接写“*槽位”，两种写法最终走同一条绑定路径。
    _bind_legacy_counter(value, table)
    _bind_legacy_status(value, table)
    _bind_legacy_judgement(value, table)
    _bind_legacy_rule(value, table)

    for key, child in tuple(value.items()):
        value[key] = _bind_value(child, root)

    for slot_key, category in SLOT_KEYS.items():
        slot = value.get(slot_key)
        if slot is None:
            continue
        if not isinstance(slot, str) or not slot.strip():
            raise ValueError(f"{slot_key}必须是非空字符串")
        term = dict(resolve_term(root, category, slot.strip()))
        if category == "计量":
            value["计量"] = slot.strip()
            if "上限" in term:
                value["最高值"] = term["上限"]
            value["计量显示名"] = term.get("名称", slot.strip())
        elif category == "状态":
            term = {
                key: child
                for key, child in term.items()
                if key not in {"兼容名", "原名"}
            }
            current = value.get("状态")
            if current is None:
                value["状态"] = term
            elif isinstance(current, dict):
                merged = {**term, **current}
                if term.get("名称"):
                    merged["名称"] = term["名称"]
                value["状态"] = merged
        elif category == "规则":
            value["名称"] = term.get("名称", slot.strip())
            if "规则" in term:
                value["规则"] = deepcopy(term["规则"])
            if "重复处理" in term:
                value["重复处理"] = term["重复处理"]
            if "来源退场时移除" in term:
                value["来源退场时移除"] = term["来源退场时移除"]
        elif category == "判定":
            value["判定"] = term.get("判定", slot.strip())
            value["方式"] = term.get("方式", "必定成功")
            if "次数" in term:
                value["次数"] = term["次数"]
    return value


def _term_slot(table: Mapping[str, Any], category: str, raw: str) -> str | None:
    category_table = table.get(category)
    if not isinstance(category_table, Mapping):
        return None
    text = str(raw or "").strip()
    if text in category_table:
        return text
    for slot, definition in category_table.items():
        if not isinstance(definition, Mapping):
            continue
        aliases = definition.get("兼容名") or definition.get("原名") or ()
        if isinstance(aliases, str):
            aliases = (aliases,)
        if text in {str(item).strip() for item in aliases}:
            return str(slot)
    return None


def _bind_legacy_counter(value: dict[str, Any], table: Mapping[str, Any]) -> None:
    if "计量槽位" in value or not isinstance(value.get("计量"), str):
        return
    slot = _term_slot(table, "计量", value["计量"])
    if slot:
        value["计量槽位"] = slot


def _bind_legacy_status(value: dict[str, Any], table: Mapping[str, Any]) -> None:
    status = value.get("状态")
    if "状态槽位" in value or not isinstance(status, Mapping):
        return
    name = status.get("名称")
    slot = _term_slot(table, "状态", str(name or ""))
    if slot:
        value["状态槽位"] = slot


def _bind_legacy_judgement(value: dict[str, Any], table: Mapping[str, Any]) -> None:
    if "判定槽位" in value or not isinstance(value.get("判定"), str):
        return
    slot = _term_slot(table, "判定", value["判定"])
    if slot:
        value["判定槽位"] = slot


def _bind_legacy_rule(value: dict[str, Any], table: Mapping[str, Any]) -> None:
    if "规则槽位" in value or not isinstance(value.get("名称"), str):
        return
    slot = _term_slot(table, "规则", value["名称"])
    if slot:
        value["规则槽位"] = slot


__all__ = [
    "TERM_CATEGORIES",
    "SLOT_KEYS",
    "bind_term_slots",
    "construct_term_table",
    "resolve_term",
]
