"""五行 JSON 契约的公共解释函数。"""

from __future__ import annotations

import random
from collections.abc import Mapping
from typing import Any

ELEMENTS = ("木", "火", "土", "金", "水")


def generate_five_elements(
    rules: Mapping[str, Any], source: random.Random
) -> dict[str, float]:
    """按 JSON 的主次定值规则生成一份总和为 100 的角色根性。"""

    generation = _mapping(rules.get("根性生成"), "五行.根性生成")
    if generation.get("算法") != "主次定值":
        raise ValueError("战斗核心不支持当前五行根性生成算法")
    main = _number(generation.get("主属性"), "五行.根性生成.主属性")
    secondary = _number(generation.get("次属性"), "五行.根性生成.次属性")
    remainder = _number(generation.get("余属性"), "五行.根性生成.余属性")
    values = [main, secondary, remainder, remainder, remainder]
    total = _number(generation.get("总和"), "五行.根性生成.总和")
    if abs(sum(values) - total) > 1e-6:
        raise ValueError("五行根性生成数值之和必须等于总和")
    order = list(ELEMENTS)
    source.shuffle(order)
    result = {element: 0.0 for element in ELEMENTS}
    for element, amount in zip(order, values, strict=True):
        result[element] = amount
    return result


def relation_maps(
    rules: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    return _relation_map(rules.get("相生"), "相生"), _relation_map(
        rules.get("相克"), "相克"
    )


def _relation_map(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, list):
        raise TypeError(f"五行.{label}必须是数组")
    result: dict[str, str] = {}
    for index, raw in enumerate(value):
        row = _mapping(raw, f"五行.{label}[{index}]")
        source = str(row.get("来源") or "")
        target = str(row.get("目标") or "")
        if source not in ELEMENTS or target not in ELEMENTS or source in result:
            raise ValueError(f"五行.{label}[{index}]关系无效")
        result[source] = target
    if set(result) != set(ELEMENTS):
        raise ValueError(f"五行.{label}必须覆盖木火土金水")
    return result


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label}必须是对象")
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label}必须是数字")
    return float(value)


__all__ = ["ELEMENTS", "generate_five_elements", "relation_maps"]
