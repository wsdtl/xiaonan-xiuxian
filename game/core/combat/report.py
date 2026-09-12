"""把战斗结算转换为前端只需渲染的公开战报。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .catalog import BattleReportCatalog
from .contracts import (
    BattleEvent,
    CombatFieldResult,
    CombatFormationResult,
    CombatResult,
    StatusResult,
)


@dataclass(frozen=True)
class RuntimeBattleReportParticipant:
    id: str
    name: str
    title: str
    attributes: Mapping[str, float]
    initial_health: float
    final_health: float
    initial_spirit: float = 0.0
    final_spirit: float = 0.0
    initial_shield: float = 0.0
    final_shield: float = 0.0
    initial_statuses: Sequence[StatusResult | Mapping[str, Any]] = ()
    statuses: Sequence[StatusResult | Mapping[str, Any]] = ()
    techniques: Sequence[Mapping[str, Any]] = ()
    moves: Sequence[str] = ()
    abilities: Sequence[str] = ()
    ability_definitions: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    color: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)
    level: int = 1
    combatant_type: str = "修士"


def build_battle_report(
    outcome: CombatResult,
    participants: Sequence[RuntimeBattleReportParticipant],
    *,
    catalog: BattleReportCatalog,
    seed: int | None = None,
    generated_at: str | None = None,
    scene: str = "青岚山演武台",
) -> dict[str, Any]:
    """生成 `晓楠修仙.战报.v1`；前端不再解释战斗事件。

    本函数只做校验、取色、按段拼装；每一段各自成函数（见下方 `_*_section` 与
    `_event_*`）。战报的字段形状是**对外契约**，改这里等于改前端要看的东西。
    """

    left_results = outcome.left_results
    right_results = outcome.right_results
    outcome_results = (*left_results, *right_results)
    _validate_report_participants(participants, outcome_results)

    palette = catalog.participant_colors
    participant_colors = {
        value.id: value.color or palette[index % len(palette)]
        for index, value in enumerate(participants)
    }
    participants_by_id = {value.id: value for value in participants}
    formations_by_id = {value.formation_id: value for value in outcome.formations}
    event_reports = _event_reports(
        outcome, participants_by_id, participant_colors, formations_by_id, catalog
    )
    filters = _event_filters(catalog, event_reports)
    winner_ids, winner_names, winner_id = _winner_section(
        outcome, left_results, right_results, outcome_results, participants_by_id
    )
    participant_reports = _participant_reports(
        participants, participant_colors, outcome, winner_ids, catalog
    )
    result_title = _result_title(outcome, winner_names)
    left_names = _side_names(participants_by_id, left_results)
    right_names = _side_names(participants_by_id, right_results)

    report = {
        "schema": catalog.report_schema,
        "generated_at": generated_at
        or datetime.now().astimezone().isoformat(timespec="seconds"),
        "scene": scene,
        "headline": f"{left_names} 对阵 {right_names}",
        "system": dict(catalog.system),
        "result": _result_section(
            outcome,
            title=result_title,
            winner_id=winner_id,
            winner_ids=winner_ids,
            event_count=len(event_reports),
            seed=seed,
        ),
        "view_modes": catalog.view_modes,
        "filters": filters,
        "participants": participant_reports,
        "events": event_reports,
    }
    if outcome.field is not None:
        report["field"] = _field_report(outcome.field, outcome.events)
    if outcome.formations:
        report["formations"] = [
            _formation_report(value, outcome.events) for value in outcome.formations
        ]
    return report


def _validate_report_participants(
    participants: Sequence[RuntimeBattleReportParticipant],
    outcome_results: Sequence[Any],
) -> None:
    """战报的参战者必须与战斗结果**完全对得上**：数量、编号、类别与等级。"""

    if len(participants) < 2:
        raise ValueError("战报至少需要两名参战者")
    if len({value.id for value in participants}) != len(participants):
        raise ValueError("战报参战者 ID 不能重复")
    outcome_ids = {value.id for value in outcome_results}
    participant_ids = {value.id for value in participants}
    if participant_ids != outcome_ids:
        raise ValueError("战报参战者必须与战斗结果中的全部参战者一致")
    outcome_by_id = {value.id: value for value in outcome_results}
    for participant in participants:
        result = outcome_by_id[participant.id]
        if (
            int(participant.level) != result.level
            or str(participant.combatant_type) != result.combatant_type
        ):
            raise ValueError(
                f"战报参战者类别或等级与战斗结果不一致：{participant.name}"
            )


def _event_reports(
    outcome: CombatResult,
    participants_by_id: Mapping[str, RuntimeBattleReportParticipant],
    participant_colors: Mapping[str, str],
    formations_by_id: Mapping[str, Any],
    catalog: BattleReportCatalog,
) -> list[dict[str, Any]]:
    """逐个事件转写；序号从 1 起。"""

    return [
        _event_report(
            event,
            index + 1,
            participants_by_id,
            participant_colors,
            formations_by_id,
            catalog,
        )
        for index, event in enumerate(outcome.events)
    ]


def _event_filters(
    catalog: BattleReportCatalog, event_reports: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """事件分类筛选器：`all` 取全部条数，其余按分类计数补齐。"""

    category_counts = Counter(event["category"] for event in event_reports)
    filters = []
    for definition in catalog.category_definitions:
        category_id = definition["id"]
        filters.append(
            {
                **definition,
                "count": len(event_reports)
                if category_id == "all"
                else category_counts.get(category_id, 0),
            }
        )
    return filters


def _winner_section(
    outcome: CombatResult,
    left_results: Sequence[Any],
    right_results: Sequence[Any],
    outcome_results: Sequence[Any],
    participants_by_id: Mapping[str, RuntimeBattleReportParticipant],
) -> tuple[set[str], list[str], str]:
    """返回（胜方编号集合、胜者名、胜者编号）。平局时集合为空。"""

    left_ids = {value.id for value in left_results}
    right_ids = {value.id for value in right_results}
    winner_ids = (
        left_ids
        if outcome.winner_side == "left"
        else right_ids
        if outcome.winner_side == "right"
        else set()
    )
    winner_names = [
        participants_by_id[value.id].name
        for value in outcome_results
        if value.id in winner_ids
    ]
    winner_id = outcome.winner_id or ""
    return winner_ids, winner_names, winner_id


def _participant_reports(
    participants: Sequence[RuntimeBattleReportParticipant],
    participant_colors: Mapping[str, str],
    outcome: CombatResult,
    winner_ids: set[str],
    catalog: BattleReportCatalog,
) -> list[dict[str, Any]]:
    """逐个参战者转写；胜负标签按平局 / 在胜方 / 其余三档。"""

    return [
        _participant_report(
            value,
            number=index + 1,
            color=participant_colors[value.id],
            outcome_label="平" if outcome.draw else "胜" if value.id in winner_ids else "负",
            events=outcome.events,
            catalog=catalog,
        )
        for index, value in enumerate(participants)
    ]


def _result_title(outcome: CombatResult, winner_names: Sequence[str]) -> str:
    return "胜负未分" if outcome.draw else f"{'、'.join(winner_names)}取胜"


def _side_names(
    participants_by_id: Mapping[str, RuntimeBattleReportParticipant],
    results: Sequence[Any],
) -> str:
    return "、".join(participants_by_id[value.id].name for value in results)


def _result_section(
    outcome: CombatResult,
    *,
    title: str,
    winner_id: str,
    winner_ids: set[str],
    event_count: int,
    seed: int | None,
) -> dict[str, Any]:
    """战报的结论块：前端只看这里判胜负。"""

    return {
        "code": (
            "draw"
            if outcome.draw
            else "victory"
            if outcome.winner_side == "left"
            else "defeat"
        ),
        "title": title,
        "description": f"历经 {outcome.actions} 次行动，{title}。",
        "actions": outcome.actions,
        "event_count": event_count,
        "trigger_count": outcome.trigger_activations,
        "winner_id": winner_id or None,
        "winner_ids": [
            value.id
            for value in (*outcome.left_results, *outcome.right_results)
            if value.id in winner_ids
        ],
        "seed": seed,
    }


def _field_report(
    field: CombatFieldResult,
    events: Sequence[BattleEvent],
) -> dict[str, Any]:
    xy = (
        {"x": field.xy[0], "y": field.xy[1]}
        if field.xy is not None
        else None
    )
    changes = [
        {
            "turn": event.turn,
            "from": str(event.values.get("原阶段") or ""),
            "to": str(event.values.get("新阶段") or ""),
            "accumulated_damage": _round(
                float(event.values.get("累计承伤") or 0)
            ),
            "damage_ratio": _round(float(event.values.get("承伤比例") or 0)),
        }
        for event in events
        if event.kind == "地势变化后"
    ]
    return {
        "environment_id": field.environment_id,
        "name": field.name,
        "origin": field.origin,
        "scene": field.scene,
        "xy": xy,
        "altitude": field.altitude,
        "terrain": field.terrain,
        "stage_index": field.stage_index,
        "stage_name": field.stage_name,
        "accumulated_damage": _round(field.accumulated_damage),
        "health_basis": _round(field.health_basis),
        "damage_ratio": _round(field.damage_ratio),
        "stage_changes": changes,
    }


def _participant_report(
    participant: RuntimeBattleReportParticipant,
    *,
    number: int,
    color: str,
    outcome_label: str,
    events: Sequence[BattleEvent],
    catalog: BattleReportCatalog,
) -> dict[str, Any]:
    damage = sum(
        event.amount
        for event in events
        if event.kind in catalog.settlement_kinds("角色伤害")
        and event.source_id == participant.id
    )
    recovery = sum(
        event.amount
        for event in events
        if event.kind in catalog.settlement_kinds("资源恢复")
        and event.source_id == participant.id
    )
    abilities = {
        event.ability
        for event in events
        if event.source_id == participant.id and event.ability
    }
    abilities.update(str(value) for value in participant.abilities if str(value).strip())

    health_max = max(1.0, float(participant.attributes.get("血气上限", 1.0)))
    spirit_max = max(0.0, float(participant.attributes.get("精神上限", 0.0)))
    shield_max = max(0.0, float(participant.attributes.get("护盾上限", 0.0)))
    resources = [
        _resource("health", participant.final_health, health_max, catalog),
    ]
    if spirit_max > 0 or participant.final_spirit > 0:
        resources.append(_resource("spirit", participant.final_spirit, spirit_max, catalog))
    if shield_max > 0 or participant.final_shield > 0:
        resources.append(_resource("shield", participant.final_shield, shield_max, catalog))

    return {
        "id": participant.id,
        "number": number,
        "name": participant.name,
        "title": participant.title,
        "level": max(1, int(participant.level)),
        "combatant_type": str(participant.combatant_type or "参战者"),
        "color": color,
        "outcome": outcome_label,
        "resources": resources,
        "initial_resources": {
            "health": _round(participant.initial_health),
            "spirit": _round(participant.initial_spirit),
            "shield": _round(participant.initial_shield),
        },
        "totals": [
            {"label": "造成伤害", "value": _number_text(damage)},
            {"label": "恢复资源", "value": _number_text(recovery)},
            {"label": "触发能力", "value": str(len(abilities))},
        ],
        "attributes": [
            {
                "key": key,
                "label": key,
                "value": _round(float(participant.attributes.get(key, 0.0))),
                "display": _attribute_text(
                    key,
                    float(participant.attributes.get(key, 0.0)),
                    catalog,
                ),
            }
            for key in catalog.attribute_summary
            if float(participant.attributes.get(key, 0.0)) != 0
        ],
        "techniques": [
            _technique_report(
                value,
                catalog,
                participant.ability_definitions,
            )
            for value in participant.techniques
        ],
        "moves": [str(value) for value in participant.moves if str(value).strip()],
        "abilities": sorted(abilities),
        "statuses": [_status_report(value) for value in participant.statuses],
        "initial_statuses": [
            _status_report(value) for value in participant.initial_statuses
        ],
        "extra": dict(participant.extra),
    }


def _event_report(
    event: BattleEvent,
    sequence: int,
    participants: Mapping[str, RuntimeBattleReportParticipant],
    colors: Mapping[str, str],
    formations: Mapping[str, CombatFormationResult],
    catalog: BattleReportCatalog,
) -> dict[str, Any]:
    category = catalog.normalized_category(event.kind)
    category_definition = catalog.normalized_category_definition(category)
    is_system = event.kind in catalog.system_kinds
    formation_id = str(event.values.get("阵法编号") or "")
    formation = formations.get(formation_id)
    source = _actor_report(
        "system"
        if is_system
        else f"阵法:{formation_id}"
        if formation is not None and event.kind.startswith("阵法")
        else event.source_id,
        str(catalog.system["name"])
        if is_system
        else formation.name
        if formation is not None and event.kind.startswith("阵法")
        else event.source,
        participants,
        colors,
        catalog,
    )
    target_formation_id = (
        str(event.values.get("冲击目标") or "")
        if event.values.get("是否命中阵法")
        else ""
    )
    target_formation = formations.get(target_formation_id)
    target = _actor_report(
        f"阵法:{target_formation_id}" if target_formation is not None else event.target_id,
        target_formation.name if target_formation is not None else event.target,
        participants,
        colors,
        catalog,
    )
    details = [
        {
            "label": str(key),
            "value": _json_value(value),
            "display": _detail_text(str(key), value, catalog),
        }
        for key, value in event.values.items()
        if key != "技能键"
    ]
    steps = [
        {
            "label": key.replace("伤害", "") or "伤害",
            "value": _round(float(event.values[key])),
            "display": _number_text(float(event.values[key])),
        }
        for key in catalog.damage_steps
        if isinstance(event.values.get(key), int | float)
        and not isinstance(event.values.get(key), bool)
    ]
    amount_text = ""
    if event.amount > 0 and category == "damage":
        amount_text = f"{_number_text(event.amount)} 伤害"
    elif event.amount > 0 and category == "recover":
        amount_text = f"{_number_text(event.amount)} 恢复"

    return {
        "sequence": sequence,
        "turn": event.turn,
        "turn_label": "开战" if event.turn == 0 else f"第 {event.turn} 次行动",
        "kind": event.kind,
        "kind_label": catalog.kind_label(event.kind),
        "category": category,
        "category_label": category_definition["label"],
        "category_color": category_definition["color"],
        "compact_visible": event.kind not in catalog.compact_hidden_kinds,
        "source": source,
        "target": target,
        "text": event.text,
        "amount": _round(event.amount),
        "amount_text": amount_text,
        "ability": event.ability,
        "tags": list(event.tags),
        "steps": steps,
        "details": details,
    }


def _formation_report(
    formation: CombatFormationResult,
    events: Sequence[BattleEvent],
) -> dict[str, Any]:
    impacts = [
        event
        for event in events
        if event.kind == "阵法冲击后"
        and str(event.values.get("阵法编号") or "") == formation.formation_id
    ]
    return {
        "id": formation.formation_id,
        "name": formation.name,
        "grade": formation.grade,
        "side": "left" if formation.side == 0 else "right",
        "position": formation.position,
        "capacity": _round(formation.capacity),
        "remaining_capacity": _round(formation.remaining_capacity),
        "impact": _round(formation.impact),
        "nodes": formation.nodes,
        "rotations": formation.rotations,
        "collapsed": formation.collapsed,
        "total_impact": _round(sum(event.amount for event in impacts)),
        "impact_count": len(impacts),
    }


def _actor_report(
    actor_id: str,
    fallback_name: str,
    participants: Mapping[str, RuntimeBattleReportParticipant],
    colors: Mapping[str, str],
    catalog: BattleReportCatalog,
) -> dict[str, Any]:
    participant = participants.get(actor_id)
    if participant is None:
        return {
            "id": actor_id or "system",
            "name": fallback_name or str(catalog.system["name"]),
            "number": None,
            "color": str(catalog.system["color"]),
        }
    ids = list(participants)
    return {
        "id": participant.id,
        "name": participant.name,
        "number": ids.index(participant.id) + 1,
        "color": colors[participant.id],
    }


def _resource(
    resource_id: str,
    current: float,
    maximum: float,
    catalog: BattleReportCatalog,
) -> dict[str, Any]:
    definition = catalog.resources[resource_id]
    maximum = max(0.0, float(maximum))
    current = max(0.0, min(maximum, float(current))) if maximum else max(0.0, float(current))
    return {
        "id": resource_id,
        "label": definition["label"],
        "current": _round(current),
        "maximum": _round(maximum),
        "display": f"{_number_text(current)} / {_number_text(maximum)}",
        "percent": round(current / maximum * 100, 2) if maximum else 0,
        "color": definition["color"],
    }


def _technique_report(
    value: Mapping[str, Any],
    catalog: BattleReportCatalog,
    ability_definitions: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    active: Mapping[str, Any] = {}
    abilities: list[str] = []
    fixed_attributes: dict[str, float] = {}
    for raw_node in value.get("能力") or ():
        if not isinstance(raw_node, Mapping):
            continue
        node = dict(raw_node)
        executor = _ability_executor(node, ability_definitions)
        if executor == "装配主动技能" and not active:
            active = node
        elif executor == "装配属性":
            fixed_attributes.update(
                {
                    str(key): float(amount)
                    for key, amount in dict(node.get("属性") or {}).items()
                }
            )
        if executor in {"装配主动技能", "装配被动技能"}:
            name = str(node.get("名称") or "").strip()
            if name:
                abilities.append(name)

    return {
        "section": str(value.get("来源类别") or ""),
        "name": str(value.get("名称") or "未命名构筑"),
        "grade": str(value.get("品级") or ""),
        "born_order": int(value.get("出生序号") or 0),
        "move": str(active.get("名称") or ""),
        "abilities": list(dict.fromkeys(abilities)),
        "fixed_attributes": fixed_attributes,
    }


def _ability_executor(
    value: Mapping[str, Any],
    definitions: Mapping[str, Mapping[str, Any]] | None,
) -> str:
    ability = str(value.get("能力") or "")
    if definitions and ability in definitions:
        return str(definitions[ability].get("执行器") or ability)
    return ability


def _status_report(value: StatusResult | Mapping[str, Any]) -> dict[str, Any]:
    status = value.to_dict() if isinstance(value, StatusResult) else dict(value)
    return {
        "name": str(status.get("名称") or "未知状态"),
        "category": str(status.get("类别") or "中性"),
        "turns": max(0, int(status.get("剩余行动") or 0)),
        "stacks": max(1, int(status.get("层数") or 1)),
        "source": str(status.get("来源名称") or status.get("来源") or ""),
    }


def _detail_text(key: str, value: Any, catalog: BattleReportCatalog) -> str:
    if value is None:
        return "未进行判定"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, int | float):
        if key in catalog.percent_details:
            return _percent_text(float(value))
        if key in catalog.multiplier_details:
            return f"{_number_text(float(value))} 倍"
        return _number_text(float(value))
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return "、".join(str(item) for item in value)
    return str(value)


def _attribute_text(key: str, value: float, catalog: BattleReportCatalog) -> str:
    if key in catalog.percent_attributes:
        return f"{_number_text(value)}%"
    return _number_text(value)


def _percent_text(value: float) -> str:
    return f"{_number_text(value * 100)}%"


def _number_text(value: float) -> str:
    rounded = round(float(value), 2)
    return str(int(rounded)) if rounded.is_integer() else f"{rounded:.2f}".rstrip("0").rstrip(".")


def _round(value: float) -> float | int:
    rounded = round(float(value), 3)
    return int(rounded) if rounded.is_integer() else rounded


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int | float):
        return _round(float(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence):
        return [_json_value(item) for item in value]
    return str(value)
