"""种族登记表的唯一结构读取入口。"""

from __future__ import annotations

from collections.abc import Mapping

from game.core.data import (
    JsonDataError,
    JsonDataService,
    mapping,
    sequence,
    strict_text,
)


def load_races(data: JsonDataService) -> dict[str, Mapping[str, object]]:
    """读并校验种族登记表；结构读不通就拒绝启动。

    语义（登记过 / 正负配对 / 名额）由判据查，这里只保证结构可解释。
    """

    entries = data.entities("种族")
    result: dict[str, Mapping[str, object]] = {}
    numbers: dict[str, str] = {}
    for race_id, raw in entries.items():
        where = f"种族[{race_id}]"
        entry = mapping(raw, where)
        name = strict_text(entry.get("名称"), f"{where}.名称")
        if name in result:
            raise JsonDataError(f"{where}.种族重名：{name}")
        for rule_index, rule in enumerate(
            sequence(entry.get("天生规则") or (), f"{where}.天生规则")
        ):
            node = mapping(rule, f"{where}.天生规则[{rule_index}]")
            strict_text(node.get("名称"), f"{where}.天生规则[{rule_index}].名称")
        lifespan_factor = entry.get("寿元系数")
        if lifespan_factor is not None:
            try:
                factor = float(lifespan_factor)
            except (TypeError, ValueError) as exc:
                raise JsonDataError(f"{where}.寿元系数必须是数字") from exc
            if not factor > 0:
                raise JsonDataError(f"{where}.寿元系数必须大于 0")
        number = strict_text(entry.get("编号"), f"{where}.编号")
        if number in numbers:
            raise JsonDataError(f"{where}.编号重复：{number}")
        numbers[number] = name
        result[name] = entry
    return result


__all__ = ["load_races"]
