"""把原始战报投影成前端动画契约（game.battle_animation v1）。

只读原始 report，不读文本展示包；文本模式与动画模式共用同一份战报。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .catalog import BattleReportCatalog

DEFAULT_PACING = {"行动": 900, "事件": 220, "多段": 160, "收尾": 800}
_RESOURCE_LABELS = {"血气": "health", "神魂": "soul", "精神": "spirit", "护盾": "shield"}
_STATUS_CATEGORIES = {"正面", "负面", "控制", "中性"}


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    if isinstance(value, bool) or value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any, default: str = "") -> str:
    return str(value) if value is not None else default


def _details(event: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in event.get("details") or ():
        if isinstance(item, Mapping) and item.get("label"):
            result[str(item["label"])] = item.get("value")
    return result


def _event_ref(value: Any, formations: Mapping[str, str]) -> str:
    raw = _text(value)
    if raw.startswith("阵法:"):
        number = raw.split(":", 1)[1]
        return formations.get(number, f"formation:{number}")
    if raw.startswith("战场环境:"):
        return "environment"
    return raw or "system"


def _unit_ref(value: Any) -> str:
    return _text(value) or "system"


def _resource_key(value: Any) -> str:
    return _RESOURCE_LABELS.get(_text(value), "health")


def _status_category(value: Any) -> str:
    category = _text(value, "中性")
    return category if category in _STATUS_CATEGORIES else "中性"


def _status_snapshot(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    name = _text(raw.get("名称") or raw.get("name"))
    if not name:
        return None
    return {
        "name": name,
        "category": _status_category(raw.get("类别") or raw.get("category")),
        "stacks": max(1, _integer(raw.get("层数") or raw.get("stacks"), 1)),
        "duration": max(0, _integer(raw.get("剩余行动") or raw.get("duration"), 0)),
    }


def _unit(participant: Mapping[str, Any]) -> dict[str, Any]:
    raw_attributes = participant.get("attributes") or {}
    if isinstance(raw_attributes, Mapping):
        attributes = dict(raw_attributes)
    else:
        attributes = {
            str(item.get("key")): item.get("value")
            for item in raw_attributes
            if isinstance(item, Mapping) and item.get("key")
        }
    resources = {
        str(value.get("id")): dict(value)
        for value in participant.get("resources") or ()
        if isinstance(value, Mapping)
    }
    initial = dict(participant.get("initial_resources") or {})
    health_max = _number(attributes.get("血气上限"), _number((resources.get("health") or {}).get("maximum"), 0.0))
    soul_max = _number(
        attributes.get("神魂上限"),
        _number(participant.get("initial_soul"), 0.0),
    )
    spirit_max = _number(attributes.get("精神上限"), _number((resources.get("spirit") or {}).get("maximum"), 0.0))
    shield_max = _number((resources.get("shield") or {}).get("maximum"), 0.0)
    if shield_max <= 0:
        shield_max = max(0.0, health_max * _number(attributes.get("护盾上限"), 0.0) / 100.0)
    start_health = _number(initial.get("health"), health_max)
    start_soul = _number(initial.get("soul"), _number(participant.get("initial_soul"), soul_max))
    start_spirit = _number(initial.get("spirit"), 0.0)
    start_shield = _number(initial.get("shield"), 0.0)
    statuses = [
        value
        for value in (_status_snapshot(item) for item in participant.get("initial_statuses") or ())
        if value is not None
    ]
    raw_id = _text(participant.get("id"))
    name = _text(participant.get("name"), raw_id)
    kind = "player" if raw_id.startswith("player:") else "companion" if raw_id.startswith("companion:") else "other"
    qq = ""
    if kind == "player":
        qq = raw_id.split(":", 1)[1]
    elif kind == "companion":
        parts = raw_id.split(":", 2)
        qq = parts[1] if len(parts) > 1 else ""
    avatar_text = qq[:1] if kind == "player" and qq else (name[:1] or "?")
    return {
        "id": raw_id,
        "name": name,
        "content_id": _text(participant.get("content_id")),
        "kind": kind,
        "qq": qq,
        "avatar_text": avatar_text,
        "group": _text(participant.get("group_id")),
        "side": (
            participant.get("side")
            if participant.get("side") in {"left", "right"}
            else ("left" if _number(participant.get("side"), 0) == 0 else "right")
        ),
        "level": max(1, _integer(participant.get("level"), 1)),
        "color": _text(participant.get("color")),
        "max": {
            "health": max(0.0, health_max),
            "soul": max(0.0, soul_max),
            "spirit": max(0.0, spirit_max),
            "shield": max(0.0, shield_max),
        },
        "start": {
            "health": max(0.0, start_health),
            "soul": max(0.0, start_soul),
            "spirit": max(0.0, start_spirit),
            "shield": max(0.0, start_shield),
        },
        "statuses": statuses,
    }


def _formations(report: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    rows: list[dict[str, Any]] = []
    mapping: dict[str, str] = {}
    for raw in report.get("formations") or ():
        if not isinstance(raw, Mapping):
            continue
        number = _text(raw.get("id"))
        ref = f"formation:{number}"
        mapping[number] = ref
        rows.append({
            "id": ref,
            "side": _text(raw.get("side"), "left"),
            "name": _text(raw.get("name"), number),
            "grade": _text(raw.get("grade")),
            "owner_group": _text(raw.get("owner_group")),
            "capacity": _number(raw.get("capacity"), 0.0),
            "start_capacity": _number(raw.get("capacity"), 0.0),
            "impact": _number(raw.get("impact"), 0.0),
            "nodes": _integer(raw.get("nodes"), 0),
            "position": _integer(raw.get("position"), 0),
            "collapsed": bool(raw.get("collapsed")),
        })
    return rows, mapping


def _environment(report: Mapping[str, Any]) -> dict[str, Any] | None:
    field = report.get("field")
    if not isinstance(field, Mapping):
        return None
    changes = [value for value in field.get("stage_changes") or () if isinstance(value, Mapping)]
    stages: list[dict[str, Any]] = []
    for change in changes:
        name = _text(change.get("to"))
        if name and all(value.get("name") != name for value in stages):
            stages.append({"name": name, "damage_ratio": _number(change.get("damage_ratio"), 0.0)})
    stage = _text(field.get("stage_name"))
    if changes:
        first = _text(changes[0].get("from"))
        if first and all(value.get("name") != first for value in stages):
            stages.insert(0, {"name": first, "damage_ratio": 0.0})
    if stage and all(value.get("name") != stage for value in stages):
        stages.append({"name": stage, "damage_ratio": _number(field.get("damage_ratio"), 0.0)})
    initial_stage = _text(changes[0].get("from")) if changes else stage
    return {
        "id": f"environment:{_text(field.get('environment_id'))}",
        "name": _text(field.get("name")),
        "scene": _text(field.get("scene")),
        "stage": stage,
        "initial_stage": initial_stage,
        "initial_damage_ratio": 0.0,
        "stage_index": _integer(field.get("stage_index"), 0),
        "health_basis": _number(field.get("health_basis"), 0.0),
        "accumulated_damage": _number(field.get("accumulated_damage"), 0.0),
        "damage_ratio": _number(field.get("damage_ratio"), 0.0),
        "stages": stages,
    }


def _action_for_turn(events: Sequence[Mapping[str, Any]]) -> tuple[str, str, list[str], str]:
    actor = ""
    skill = ""
    targets: list[str] = []
    for event in events:
        kind = _text(event.get("kind"))
        source = _text((event.get("source") or {}).get("id"))
        target = _text((event.get("target") or {}).get("id"))
        if kind == "行动开始" and source:
            actor = source
        if kind in {"技能施放后", "普通攻击后", "追加攻击后"}:
            skill = _text(_details(event).get("技能"))
            if not skill:
                skill = {
                    "普通攻击后": "普通攻击",
                    "追加攻击后": "追加攻击",
                }.get(kind, "")
        if kind in {"造成伤害后", "闪避后", "恢复后", "资源恢复后", "获得护盾后", "添加状态后", "死亡后"} and target:
            targets.append(target)
        if not skill:
            skill = _text(_details(event).get("伤害名称")) or _text(event.get("ability"))
    if not actor:
        for event in events:
            source = _text((event.get("source") or {}).get("id"))
            if source and not source.startswith(("阵法:", "战场环境:", "system")):
                actor = source
                break
    unique: list[str] = []
    for value in targets:
        if value not in unique and not value.startswith("战场环境:"):
            unique.append(value)
    return actor, skill or "普通攻击", unique, ""


def _animation_kind(events: Sequence[dict[str, Any]], actor: str) -> str:
    damages = [event for event in events if event["type"] == "damage"]
    heals = [event for event in events if event["type"] == "heal"]
    shields = [event for event in events if event["type"] == "shield"]
    statuses = [event for event in events if event["type"] == "status_add"]
    if damages:
        if len({event["target"] for event in damages}) > 1:
            return "aoe"
        if len(damages) > 1:
            return "combo"
        if any(event["target"] == actor for event in heals):
            return "drain"
        return "attack"
    if heals:
        return "heal"
    if shields:
        return "shield"
    if any(event.get("category") == "控制" for event in statuses):
        return "control"
    if any(event.get("target") == actor and event.get("category") == "正面" for event in statuses):
        return "buff"
    if any(event.get("target") != actor and event.get("category") == "负面" for event in statuses):
        return "debuff"
    return "other"


def build_animation_view(report: Mapping[str, Any], catalog: BattleReportCatalog) -> dict[str, Any]:
    """从原始 report 生成一份整场动画 JSON。"""

    units = [_unit(value) for value in report.get("participants") or () if isinstance(value, Mapping)]
    formations, formation_map = _formations(report)
    environment = _environment(report)
    formation_left = {value["id"]: value["start_capacity"] for value in formations}
    paced = dict(DEFAULT_PACING)
    raw_pacing = catalog.animation_config.get("节奏")
    if isinstance(raw_pacing, Mapping):
        for key in paced:
            if key in raw_pacing:
                paced[key] = max(1, _integer(raw_pacing[key], paced[key]))

    timeline: list[dict[str, Any]] = [{"t": 0, "seq": 0, "turn": 0, "type": "battle_start"}]
    seq = 1
    last_t = 0

    def push(event: dict[str, Any]) -> None:
        nonlocal seq, last_t
        event["seq"] = seq
        seq += 1
        timeline.append(event)
        last_t = max(last_t, _integer(event.get("t"), 0))

    grouped: dict[int, list[Mapping[str, Any]]] = {}
    for event in report.get("events") or ():
        if isinstance(event, Mapping):
            grouped.setdefault(_integer(event.get("turn"), 0), []).append(event)

    for turn in sorted(grouped):
        turn_events = grouped[turn]
        actor, skill, targets, _ = _action_for_turn(turn_events)
        action_t = 200 if turn == 0 else max(last_t + 200, 200)
        mapped: list[dict[str, Any]] = []

        # 开场的阵法/环境事件先走，再让行动落在它们后面。
        for event in turn_events:
            kind = _text(event.get("kind"))
            values = _details(event)
            source_id = _text((event.get("source") or {}).get("id"))
            target_id = _text((event.get("target") or {}).get("id"))
            item: dict[str, Any] | None = None
            if kind == "阵法展开":
                number = _text(values.get("阵法编号"))
                item = {"t": 0, "turn": turn, "type": "formation_cast", "formation": formation_map.get(number, f"formation:{number}")}
            elif kind == "阵法轮转后":
                number = _text(values.get("阵法编号"))
                item = {
                    "t": 0, "turn": turn, "type": "formation_turn",
                    "formation": formation_map.get(number, f"formation:{number}"),
                    "rotation": _integer(values.get("累计轮转"), 0),
                    "detection": {
                        "label": _text(values.get("检测字段")),
                        "relation": _text(values.get("检测关系")),
                        "value": _number(values.get("检测值"), 0.0),
                        "unit": _number(values.get("检测单位"), 0.0),
                        "multiplier": _number(values.get("检测倍率"), 1.0),
                        "difficulty": _text(values.get("检测难度")),
                    },
                }
            elif kind == "阵法冲击后":
                number = _text(values.get("阵法编号"))
                hit_formation = bool(values.get("是否命中阵法"))
                ref = formation_map.get(number, f"formation:{number}")
                target_ref = (
                    formation_map.get(target_id[3:], f"formation:{target_id[3:]}")
                    if target_id.startswith("阵法:")
                    else _event_ref(target_id, formation_map)
                )
                if hit_formation:
                    before = formation_left.get(target_ref, 0.0)
                    after = max(0.0, before - _number(values.get("实际数值"), 0.0))
                    formation_left[target_ref] = after
                    item = {
                        "t": 0, "turn": turn, "type": "formation_impact",
                        "source": ref, "target": target_ref,
                        "value": _number(values.get("实际数值"), 0.0),
                        "hit_formation": True,
                        "before": before, "after": after,
                    }
                else:
                    item = {
                        "t": 0, "turn": turn, "type": "formation_impact",
                        "source": ref, "target": _event_ref(target_id, formation_map),
                        "value": _number(values.get("实际数值"), 0.0),
                        "hit_formation": False,
                        "resource": "health",
                        "before": _number(values.get("伤害前血气"), 0.0),
                        "after": _number(values.get("伤害后血气"), 0.0),
                    }
            elif kind == "阵法崩解后":
                number = _text(values.get("阵法编号"))
                item = {"t": 0, "turn": turn, "type": "formation_break", "formation": formation_map.get(number, f"formation:{number}")}
            elif kind == "地势承伤后":
                item = {
                    "t": 0, "turn": turn, "type": "environment_charge",
                    "value": _number(values.get("本次承伤"), 0.0),
                    "accumulated": _number(values.get("累计承伤"), 0.0),
                    "ratio": _number(values.get("承伤比例"), 0.0),
                    "stage": _text(values.get("阶段")),
                }
            elif kind == "地势变化后":
                item = {
                    "t": 0, "turn": turn, "type": "environment_stage",
                    "from": _text(values.get("原阶段")),
                    "to": _text(values.get("新阶段")),
                    "accumulated": _number(values.get("累计承伤"), 0.0),
                    "damage_ratio": _number(values.get("承伤比例"), 0.0),
                }
            if item is not None:
                item["t"] = max(last_t + 1, 100 if turn == 0 else action_t)
                mapped.append(item)

        if actor and not actor.startswith(("阵法:", "战场环境:", "system")):
            action = {
                "t": action_t, "turn": turn, "type": "action",
                "actor": _unit_ref(actor),
                "skill": skill,
                "targets": [_event_ref(value, formation_map) for value in targets],
                "animation": "",
            }
            mapped.insert(0, action)

        for event in turn_events:
            kind = _text(event.get("kind"))
            values = _details(event)
            source = _event_ref((event.get("source") or {}).get("id"), formation_map)
            target = _event_ref((event.get("target") or {}).get("id"), formation_map)
            item = None
            if kind == "造成伤害后":
                soul = _number(values.get("神魂伤害"), 0.0)
                health = _number(values.get("血气伤害"), 0.0)
                resource = "soul" if soul > 0 or ("伤害前神魂" in values and health <= 0) else "health"
                shield = _number(values.get("护盾伤害"), 0.0)
                value = soul if resource == "soul" else health
                if value <= 0:
                    value = max(0.0, _number(values.get("实际伤害"), 0.0) - shield)
                if value <= 0 and shield <= 0:
                    continue
                item = {
                    "t": 0, "turn": turn, "type": "damage",
                    "source": source, "target": target,
                    "resource": resource, "value": value,
                    "shield_absorbed": shield,
                    "crit": bool(values.get("暴击")),
                    "blocked": bool(values.get("格挡")),
                    "overkill": _number(values.get("过量伤害"), 0.0),
                }
                before_key = "伤害前神魂" if resource == "soul" else "伤害前血气"
                after_key = "伤害后神魂" if resource == "soul" else "伤害后血气"
                if before_key in values:
                    item["before"] = _number(values.get(before_key), 0.0)
                if after_key in values:
                    item["after"] = _number(values.get(after_key), 0.0)
            elif kind == "闪避后":
                item = {"t": 0, "turn": turn, "type": "miss", "source": source, "target": target}
            elif kind in {"恢复后", "资源恢复后", "复活后", "获得护盾后"}:
                resource = _resource_key(values.get("资源"))
                value = _number(values.get("实际数值"), 0.0)
                if kind == "复活后":
                    item = {"t": 0, "turn": turn, "type": "revive", "target": target, "resource": resource, "value": value}
                elif resource == "shield" or kind == "获得护盾后":
                    item = {"t": 0, "turn": turn, "type": "shield", "source": source, "target": target, "value": value}
                else:
                    item = {"t": 0, "turn": turn, "type": "heal", "source": source, "target": target, "resource": resource, "value": value}
                if "变化前数值" in values:
                    item["before"] = _number(values.get("变化前数值"), 0.0)
                if "变化后数值" in values:
                    item["after"] = _number(values.get("变化后数值"), 0.0)
            elif kind == "资源消耗后":
                resource = _resource_key(values.get("资源"))
                value = _number(values.get("实际数值"), 0.0)
                item = {"t": 0, "turn": turn, "type": "resource", "target": target, "resource": resource, "delta": -value, "before": _number(values.get("变化前数值"), 0.0), "after": _number(values.get("变化后数值"), 0.0)}
            elif kind == "添加状态后":
                name = _text(values.get("状态"))
                if name:
                    item = {"t": 0, "turn": turn, "type": "status_add", "source": source, "target": target, "name": name, "category": _status_category(values.get("状态类别")), "stacks": max(1, _integer(values.get("状态层数"), 1)), "duration": max(0, _integer(values.get("剩余行动"), 0))}
            elif kind == "移除状态后":
                name = _text(values.get("状态"))
                if name:
                    item = {"t": 0, "turn": turn, "type": "status_remove", "target": target, "name": name, "reason": _text(values.get("原因"))}
            elif kind == "状态层数变化后":
                name = _text(values.get("状态"))
                if name:
                    item = {"t": 0, "turn": turn, "type": "status_stack", "target": target, "name": name, "stacks": max(0, _integer(values.get("变化后数值"), 0)), "delta": _number(values.get("变化后数值"), 0.0) - _number(values.get("变化前数值"), 0.0)}
            elif kind == "死亡后":
                item = {"t": 0, "turn": turn, "type": "unit_down", "target": target}
            elif kind == "战斗结束":
                code = _text((report.get("result") or {}).get("code"), "draw")
                item = {"t": 0, "turn": turn, "type": "battle_end", "winner": code if code in {"left", "right", "draw"} else "draw"}
            if item is not None:
                item["t"] = max(last_t + paced["事件"], action_t + paced["事件"])
                mapped.append(item)

        # 同 turn 的事件按 action → 状态/伤害/环境 顺序排；t 仍可能相同，seq 保序。
        for item in mapped:
            if item["type"] == "action":
                item["animation"] = _animation_kind(mapped, item["actor"])
        for item in mapped:
            if "t" not in item or item["t"] <= 0:
                item["t"] = max(last_t + paced["事件"], action_t)
            push(item)

    duration = max(last_t + paced["收尾"], 1000)
    title = _text(report.get("headline"))
    if len(units) > 4:
        left_groups = {unit.get("group") or unit["id"] for unit in units if unit["side"] == "left"}
        right_groups = {unit.get("group") or unit["id"] for unit in units if unit["side"] == "right"}
        if left_groups and right_groups and (len(left_groups) < sum(1 for unit in units if unit["side"] == "left")):
            title = f"{len(left_groups)} 单位 对 {len(right_groups)} 单位"
        else:
            left_count = sum(1 for unit in units if unit["side"] == "left")
            right_count = sum(1 for unit in units if unit["side"] == "right")
            title = f"{left_count} 对 {right_count}"
    return {
        "schema": catalog.animation_schema,
        "version": catalog.animation_version,
        "battle": {
            "title": title,
            "scene": _text(report.get("scene")),
            "result": _text((report.get("result") or {}).get("code"), "draw"),
            "actions": _integer((report.get("result") or {}).get("actions"), 0),
            "duration": duration,
        },
        "environment": environment,
        "formations": formations,
        "units": units,
        "events": timeline,
    }


__all__ = ["build_animation_view"]
