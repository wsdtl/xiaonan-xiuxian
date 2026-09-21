"""把后端战斗记录整理为晓楠修仙战报前端使用的展示协议。"""

from __future__ import annotations

from collections import Counter, OrderedDict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from typing import Any

from .catalog import BattleReportCatalog


def build_battle_report_presentation(
    report: Mapping[str, Any],
    catalog: BattleReportCatalog,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """返回公开战报头和静态明细包；页面只负责解释这两个后端对象。"""

    if report.get("schema") != catalog.report_schema:
        raise ValueError(f"战报展示适配器只接受{catalog.report_schema}")
    schema = catalog.presentation_schema
    version = catalog.presentation_version
    ui = catalog.ui
    participants = [dict(value) for value in report.get("participants") or ()]
    if len(participants) < 2:
        raise ValueError("公开战报至少需要两名参战者")

    visuals = {
        value["id"]: {
            "key": value["id"],
            "number": int(value["number"]),
            "color": value["color"],
            "foreground": catalog.foreground,
        }
        for value in participants
    }
    sides = _sides(participants)
    team_ids = {"left": "team.left", "right": "team.right"}
    team_labels = {
        side: _team_label([value for value in participants if sides[value["id"]] == side])
        for side in team_ids
    }
    team_of = {
        value["id"]: (team_ids[sides[value["id"]]], team_labels[sides[value["id"]]])
        for value in participants
    }
    system = report["system"]
    system_visual = {
        "key": "system",
        "number": 0,
        "color": system["color"],
        "foreground": catalog.foreground,
    }
    combatants = [
        _combatant(value, visuals[value["id"]], team_of[value["id"]])
        for value in participants
    ]

    initial_state = _initial_state(participants, catalog)
    final_state = _final_state(participants, initial_state)
    initial_participants = _participant_records(
        participants, visuals, initial_state, team_of, catalog
    )
    final_participants = _participant_records(
        participants, visuals, final_state, team_of, catalog
    )

    groups = _event_groups(report.get("events") or ())
    state = deepcopy(initial_state)
    compact_timeline: list[dict[str, Any]] = []
    detailed_timeline: list[dict[str, Any]] = []
    transitions: dict[str, dict[str, Any]] = {}
    public_event_count = 0
    category_counts: Counter[str] = Counter()

    for sequence, (turn, values) in enumerate(groups.items()):
        events = [dict(value) for value in values]
        before = deepcopy(state)
        _apply_events(state, events, catalog)
        after = deepcopy(state)
        title, actor_id = _transition_title(turn, events, catalog)
        visual = visuals.get(actor_id, system_visual)
        detailed_events = [
            _public_event(
                value,
                visuals,
                system_visual,
                catalog,
            )
            for value in events
        ]
        public_event_count += len(detailed_events)
        category_counts.update(value["category"] for value in detailed_events)
        categories = list(dict.fromkeys(value["category"] for value in detailed_events))
        tone = catalog.dominant_tone(categories)
        round_label = "战斗建立" if turn == 0 else f"第 {turn} 次行动"
        facts = [
            _fact("序列", sequence),
            _fact("行动", turn),
            _fact("事件", len(detailed_events)),
        ]
        compact_events = [
            _compact_event(value, catalog)
            for value in detailed_events
            if value["kind"] not in catalog.compact_hidden_kinds
        ]
        compact_timeline.append(
            {
                "sequence": sequence,
                "title": title,
                "round_label": round_label,
                "tone": tone,
                "visual": visual,
                "categories": list(dict.fromkeys(value["category"] for value in compact_events)),
                "summary_events": compact_events,
                "comparison_available": True,
            }
        )
        detailed_timeline.append(
            {
                "sequence": sequence,
                "title": title,
                "round_label": round_label,
                "sequence_label": f"行动 {turn} · 序列 {sequence}",
                "tone": tone,
                "visual": visual,
                "categories": categories,
                "facts": facts,
                "events": detailed_events,
                "comparison": {
                    "available": True,
                    "sequence": sequence,
                    "title": ui["text"]["comparison_title"],
                },
            }
        )
        transitions[f"0:{sequence}"] = {
            "schema": schema,
            "version": version,
            "segment_index": 0,
            "sequence": sequence,
            "comparison": {
                "title": ui["text"]["comparison_title"],
                "empty_text": ui["text"]["comparison_empty"],
                "changes": _state_changes(participants, before, after, catalog),
                "before": _frame(
                    "行动前状态", round_label, participants, visuals, before, team_of, catalog
                ),
                "after": _frame(
                    "行动后状态", round_label, participants, visuals, after, team_of, catalog
                ),
            },
        }

    filters = [
        {
            **value,
            "count": public_event_count
            if value["id"] == "all"
            else category_counts.get(value["id"], 0),
        }
        for value in ui["filters"]
    ]
    segment = {
        "index": 0,
        "position_label": "1 / 1",
        "title": report["headline"],
        "outcome": report["result"]["title"],
        "started_at": report["generated_at"],
        "finished_at": report["generated_at"],
        "duration_label": f"{report['result']['actions']} 次行动",
        "system_visual": system_visual,
        "combatants": combatants,
        "initial_participants": initial_participants,
        "final_participants": final_participants,
        "counts": {
            "actions": report["result"]["actions"],
            "events": public_event_count,
        },
        "formations": deepcopy(list(report.get("formations") or ())),
        "timeline": compact_timeline,
    }
    field = report.get("field")
    field_lines = []
    if isinstance(field, Mapping):
        field_lines = [
            f"战场: {field['name']} · {field['stage_name']}",
            f"地势承伤: {field['accumulated_damage']} / {field['health_basis']}",
        ]
        xy = field.get("xy")
        if isinstance(xy, Mapping):
            field_lines.insert(
                1,
                f"xy: ({xy['x']}, {xy['y']}) · 海拔 {field['altitude']} 米",
            )
    formation_lines = [
        _formation_summary_line(value) for value in report.get("formations") or ()
    ]
    main = {
        "schema": schema,
        "version": version,
        "ui": ui,
        "document_title": f"{catalog.game_name} · {report['headline']}",
        "summary": {
            "title": report["headline"],
            "outcome": report["result"]["title"],
            "tone": catalog.result_tone(report["result"]["code"]),
            "lines": [
                f"地点: {report['scene']}",
                *field_lines,
                *formation_lines,
                f"战斗行动: {report['result']['actions']}",
                f"后端事件: {public_event_count}",
                f"触发次数: {report['result']['trigger_count']}",
            ],
        },
        "started_at": report["generated_at"],
        "finished_at": report["generated_at"],
        "time_label": _time_label(str(report["generated_at"])),
        "detail": {
            "available": True,
            "retention_notice": "",
            "segment_count": 1,
            "segments": [segment],
        },
        "game_name": catalog.game_name,
        "formations": deepcopy(list(report.get("formations") or ())),
    }
    bundle = {
        "segments": {
            "0": {"schema": schema, "version": version, "segment": segment}
        },
        "events": {
            "0": {
                "schema": schema,
                "version": version,
                "segment_index": 0,
                "filters": filters,
                "timeline": detailed_timeline,
            }
        },
        "participants": {
            "0:before": {
                "schema": schema,
                "version": version,
                "segment_index": 0,
                "snapshot": "before",
                "participants": initial_participants,
            },
            "0:after": {
                "schema": schema,
                "version": version,
                "segment_index": 0,
                "snapshot": "after",
                "participants": final_participants,
            },
        },
        "transitions": transitions,
    }
    return main, bundle


def _formation_summary_line(value: Mapping[str, Any]) -> str:
    side = "左阵" if value["side"] == "left" else "右阵"
    state = (
        "阵基已崩解"
        if value["collapsed"]
        else f"余承 {value['remaining_capacity']}"
    )
    return (
        f"{side}: {value['name']} · {value['grade']}品 · "
        f"轮转 {value['rotations']} 次 · {state}"
    )


def _sides(participants: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """每个参战者的阵营，取自战报自己写的 `阵营`。

    展示层**不许自己猜阵营**：第一版写的是「下标 0 是左方、其余是右方」，
    而战报的标题（同一次战斗、同一份数据）写的是「青岚剑修、云岫道人、孤敌悬赏、孤敌悬赏
    对阵 黑水魔修、赤炎散人、霜岭客」——**页面自己跟自己打架**：第二个修士与召唤物
    全被画到了敌方。多单位编组（宗门战、讨伐）一直是错的，只是 1v1 时看不出来。
    """

    result = {}
    for value in participants:
        side = str(value.get("side") or "")
        if side not in {"left", "right"}:
            raise ValueError(f"战报参战者缺少阵营：{value.get('name')}")
        result[value["id"]] = side
    return result


def _team_label(members: Sequence[Mapping[str, Any]]) -> str:
    """一方的单位构成：一个单位就写它自己，多个按「单位 × 数」列出。"""

    counts: OrderedDict[str, int] = OrderedDict()
    for value in members:
        title = _participant_title(value)
        counts[title] = counts.get(title, 0) + 1
    return " · ".join(
        f"{title} ×{count}" if count > 1 else title for title, count in counts.items()
    )


def _combatant(
    participant: Mapping[str, Any],
    visual: Mapping[str, Any],
    team: tuple[str, str],
) -> dict[str, Any]:
    return {
        "key": participant["id"],
        "label": participant["name"],
        "team_id": team[0],
        "team_label": team[1],
        "visual": dict(visual),
    }


def _participant_records(
    participants: Sequence[Mapping[str, Any]],
    visuals: Mapping[str, Mapping[str, Any]],
    state: Mapping[str, Mapping[str, Any]],
    team_of: Mapping[str, tuple[str, str]],
    catalog: BattleReportCatalog,
) -> list[dict[str, Any]]:
    return [
        _participant_record(
            value,
            visuals[value["id"]],
            state[value["id"]],
            team_of[value["id"]],
            catalog,
        )
        for value in participants
    ]


def _participant_record(
    participant: Mapping[str, Any],
    visual: Mapping[str, Any],
    state: Mapping[str, Any],
    team: tuple[str, str],
    catalog: BattleReportCatalog,
) -> dict[str, Any]:
    resources = state["resources"]
    gauges = []
    for key, definition in catalog.resources.items():
        resource = resources.get(key)
        if not resource:
            continue
        if key != "health" and resource["maximum"] <= 0 and resource["current"] <= 0:
            continue
        gauges.append(
            {
                "id": key,
                "label": definition["label"],
                "current": resource["current"],
                "maximum": resource["maximum"],
                "display": (
                    _number(resource["current"])
                    if definition["presentation"] == "value"
                    else f"{_number(resource['current'])} / {_number(resource['maximum'])}"
                ),
                "fill_percent": round(
                    resource["current"] / resource["maximum"] * 100,
                    2,
                )
                if resource["maximum"] > 0
                else 0,
                "tone": definition["tone"],
                "presentation": definition["presentation"],
            }
        )
    statuses = [
        {
            "label": value["name"],
            "display": _status_display(value),
            "stacks": value["stacks"],
            "remaining_turns": value["turns"],
            "tone": catalog.status_tone(value["category"]),
        }
        for value in state["statuses"].values()
    ]
    return {
        "key": participant["id"],
        "label": participant["name"],
        "team_id": team[0],
        "team_label": team[1],
        "visual": dict(visual),
        "gauges": gauges,
        "status_group": {
            "id": "temporary_effects",
            **dict(catalog.participant_presentation["状态组"]),
            "items": statuses,
        },
        "detail_label": catalog.participant_presentation["详情标题"],
        "detail_groups": _detail_groups(participant, catalog),
    }


def _detail_groups(
    participant: Mapping[str, Any],
    catalog: BattleReportCatalog,
) -> list[dict[str, Any]]:
    techniques = []
    for value in participant.get("techniques") or ():
        metadata = [
            item
            for item in (value.get("section"), value.get("grade"), value.get("move"))
            if item
        ]
        techniques.append(_item(value["name"], " · ".join(metadata)))
    attributes = [
        _item(value["label"], value["display"], value.get("value"))
        for value in participant.get("attributes") or ()
    ]
    moves = [_item(value, "") for value in participant.get("moves") or ()]
    abilities = [_item(value, "") for value in participant.get("abilities") or ()]
    totals = [
        _item(value["label"], value["value"])
        for value in participant.get("totals") or ()
    ]
    labels = catalog.participant_presentation["详情分组"]
    groups = tuple(
        _group(group_id, labels[group_id], items)
        for group_id, items in (
            ("techniques", techniques),
            ("moves", moves),
            ("abilities", abilities),
            ("attributes", attributes),
            ("settlement", totals),
        )
    )
    return [value for value in groups if value is not None]


def _participant_title(participant: Mapping[str, Any]) -> str:
    """单位标题：`修士 · Lv5`。

    `参战者` 这个兜底词是第 86 轮修掉的：这里读的键是 `kind`，而战报写的是
    `combatant_type`，于是每个单位的标题都变成「修士 · 参战者 · Lv5」——
    **键读错了不会报错，只会让人以为单位类型就叫「参战者」。**
    """

    parts = [
        str(participant.get("title") or "").strip(),
        str(participant.get("combatant_type") or "").strip(),
        f"Lv{max(1, int(participant.get('level') or 1))}",
    ]
    return " · ".join(dict.fromkeys(value for value in parts if value))


def _group(group_id: str, label: str, items: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    if not items:
        return None
    return {"id": group_id, "label": label, "items": list(items), "empty_text": ""}


def _item(label: str, display: str, value: Any = None) -> dict[str, Any]:
    result = {"id": label, "label": label, "display": display}
    if value is not None:
        result["value"] = value
    return result


def _initial_state(
    participants: Sequence[Mapping[str, Any]],
    catalog: BattleReportCatalog,
) -> dict[str, dict[str, Any]]:
    result = {}
    for participant in participants:
        definitions = {value["id"]: value for value in participant.get("resources") or ()}
        initial = participant.get("initial_resources") or {}
        resources = {}
        for key in catalog.resources:
            definition = definitions.get(key) or {}
            current = float(initial.get(key) or 0)
            maximum = float(definition.get("maximum") or max(0.0, current))
            resources[key] = {"current": current, "maximum": maximum}
        result[participant["id"]] = {
            "resources": resources,
            "statuses": {
                value["name"]: dict(value)
                for value in participant.get("initial_statuses") or ()
            },
        }
    return result


def _final_state(
    participants: Sequence[Mapping[str, Any]],
    initial: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    result = deepcopy(initial)
    for participant in participants:
        current = result[participant["id"]]
        for resource in participant.get("resources") or ():
            current["resources"][resource["id"]] = {
                "current": float(resource["current"]),
                "maximum": float(resource["maximum"]),
            }
        current["statuses"] = {
            value["name"]: dict(value) for value in participant.get("statuses") or ()
        }
    return result


def _event_groups(events: Sequence[Mapping[str, Any]]) -> OrderedDict[int, list[dict[str, Any]]]:
    result: OrderedDict[int, list[dict[str, Any]]] = OrderedDict()
    for value in events:
        turn = int(value.get("turn") or 0)
        result.setdefault(turn, []).append(dict(value))
    return result


def _apply_events(
    state: dict[str, dict[str, Any]],
    events: Sequence[Mapping[str, Any]],
    catalog: BattleReportCatalog,
) -> None:
    for event in events:
        values = {value["label"]: value.get("value") for value in event.get("details") or ()}
        source_id = event.get("source", {}).get("id")
        target_id = event.get("target", {}).get("id")
        target = state.get(target_id)
        kind = event.get("kind")
        if target and kind in (
            catalog.settlement_kinds("角色伤害")
            | catalog.settlement_kinds("战场伤害")
        ):
            if isinstance(values.get("伤害后血气"), int | float):
                target["resources"]["health"]["current"] = float(values["伤害后血气"])
            if isinstance(values.get("伤害后护盾"), int | float):
                target["resources"]["shield"]["current"] = float(values["伤害后护盾"])
        elif target and kind in (
            catalog.settlement_kinds("资源恢复")
            | catalog.settlement_kinds("资源消耗")
        ):
            resource_name = str(values.get("资源") or "")
            resource_key = catalog.resource_key(resource_name)
            if resource_key:
                resource = target["resources"][resource_key]
                if isinstance(values.get("变化后数值"), int | float):
                    resource["current"] = float(values["变化后数值"])
                else:
                    delta = float(event.get("amount") or 0)
                    if kind in catalog.settlement_kinds("资源消耗"):
                        delta = -delta
                    resource["current"] = min(
                        resource["maximum"], max(0.0, resource["current"] + delta)
                    )
        elif target and kind in catalog.settlement_kinds("状态添加"):
            name = str(values.get("状态") or event.get("ability") or event.get("text"))
            target["statuses"][name] = {
                "name": name,
                "category": str(
                    values.get("状态类别")
                    or ("负面" if target_id != source_id else "正面")
                ),
                "turns": max(0, int(values.get("剩余行动") or 0)),
                "stacks": max(1, int(values.get("状态层数") or 1)),
                "source": str(
                    values.get("来源名称")
                    or event.get("source", {}).get("name", "")
                ),
            }
        elif target and kind in catalog.settlement_kinds("状态移除"):
            name = str(values.get("状态") or event.get("text") or "").removesuffix("消散")
            target["statuses"].pop(name, None)
        if kind == "行动结束" and source_id in state:
            for status in state[source_id]["statuses"].values():
                status["turns"] = max(0, int(status["turns"]) - 1)


def _transition_title(
    turn: int,
    events: Sequence[Mapping[str, Any]],
    catalog: BattleReportCatalog,
) -> tuple[str, str]:
    if turn == 0:
        return "战斗建立", "system"
    start = next((value for value in events if value.get("kind") == "行动开始"), None)
    actor = start.get("source", {}) if start else {}
    actor_id = str(actor.get("id") or "system")
    actor_name = str(actor.get("name") or "战场")
    skill = next(
        (value for value in events if value.get("kind") == "技能施放后"), None
    )
    if skill:
        details = {value["label"]: value.get("display") for value in skill.get("details") or ()}
        return (
            f"{actor_name} 对 {skill['target']['name']} 使用 {details.get('技能') or skill['text']}",
            actor_id,
        )
    attack = next(
        (
            value
            for value in events
            if str(value.get("kind") or "")
            in catalog.settlement_kinds("角色伤害")
            and value.get("source", {}).get("id") == actor_id
        ),
        None,
    )
    if attack:
        if "普通攻击" in (attack.get("tags") or ()):
            ability = "基础攻击"
        else:
            details = {
                value["label"]: value.get("value")
                for value in attack.get("details") or ()
            }
            ability = (
                attack.get("ability")
                or details.get("伤害名称")
                or str(attack.get("text") or "普通行动")
                .split("造成", 1)[0]
                .removesuffix("暴击，")
                .removesuffix("格挡，")
            )
        return f"{actor_name} 对 {attack['target']['name']} 使用 {ability}", actor_id
    return f"{actor_name} 开始行动", actor_id


def _public_event(
    event: Mapping[str, Any],
    visuals: Mapping[str, Mapping[str, Any]],
    system_visual: Mapping[str, Any],
    catalog: BattleReportCatalog,
) -> dict[str, Any]:
    source = dict(event.get("source") or {})
    target = dict(event.get("target") or {})
    category = _event_category(event, catalog)
    details = list(event.get("details") or ())
    if category == "damage":
        details = [value for value in details if value.get("label") in catalog.damage_facts]
    details = [value for value in details if value.get("label") not in catalog.internal_details]
    # 每条事实只带**给玩家看的那两个字段**：标签与显示串。原先还跟着 `key`（与标签同值）
    # 与 `value`（原值，页面从不读），一条事实三个键里两个是白带的——这里只留要用的。
    facts = [
        {"label": str(value.get("label") or ""), "display": str(value.get("display") or "")}
        for value in details
    ]
    return {
        "kind": event.get("kind", "unknown"),
        "label": event.get("kind_label") or event.get("kind") or "事件",
        "tone": _event_tone(category, str(event.get("kind") or ""), catalog),
        "category": category,
        "text": _sentence(event),
        "source": {"key": source.get("id", "system"), "label": source.get("name", "战场")},
        "target": {"key": target.get("id", "system"), "label": target.get("name", "战场")},
        "facts": facts,
        "visual": dict(visuals.get(source.get("id"), system_visual)),
    }


def _sentence(event: Mapping[str, Any]) -> str:
    """事件自己的正文；**它只是把类型名抄一遍时算没有正文**。

    引擎给多数事件填的 `text` 就是事件类型（`命中后`、`造成伤害后`），那不是正文。
    以前前端把 `text` 当句子直接印出来，战斗记录里于是全是这些内部阶段名，
    一条数字都没有（第 86 轮实测：160 条紧凑事件里 137 条短于 7 个字）。
    这里换掉，让紧凑行改由声明的关键事实拼（见 `_compact_text`）。
    """

    text = str(event.get("text") or "").strip()
    if text and text not in {str(event.get("kind") or ""), str(event.get("kind_label") or "")}:
        return text
    return ""


def _compact_event(event: Mapping[str, Any], catalog: BattleReportCatalog) -> dict[str, Any]:
    result = {
        key: deepcopy(event[key])
        for key in ("kind", "label", "tone", "category", "source", "target", "visual")
    }
    result["text"] = _compact_text(event, catalog)
    return result


def _compact_text(event: Mapping[str, Any], catalog: BattleReportCatalog) -> str:
    """紧凑行：事件自带正文就用正文，否则「类型名 · 声明的关键事实」。

    关键事实住 `战报.json` 的 `标准化.紧凑事实`，按事件类型声明：伤害类报实际伤害、
    资源类报资源与数值、状态类报状态名与层数。**渲染层不参与判断**——
    它只负责把这一行印出来。
    """

    sentence = _sentence(event)
    if sentence:
        return sentence
    facts = {str(value["label"]): value for value in event.get("facts") or ()}
    parts = []
    for entry in catalog.compact_facts.get(str(event.get("kind") or ""), ()):
        displays = [
            str(facts[name].get("display") or "").strip()
            for name in entry
            if name in facts and str(facts[name].get("display") or "").strip()
        ]
        if displays:
            parts.append(" → ".join(displays))
    if not parts:
        return str(event.get("label") or "事件")
    return f"{event.get('label') or '事件'} · {' '.join(parts)}"


def _event_category(
    event: Mapping[str, Any],
    catalog: BattleReportCatalog,
) -> str:
    kind = str(event.get("kind") or "")
    value = str(event.get("category") or "")
    return catalog.public_category(kind, value)


def _event_tone(
    category: str,
    kind: str,
    catalog: BattleReportCatalog,
) -> str:
    return catalog.event_tone(category, kind)


def _frame(
    title: str,
    label: str,
    participants: Sequence[Mapping[str, Any]],
    visuals: Mapping[str, Mapping[str, Any]],
    state: Mapping[str, Mapping[str, Any]],
    team_of: Mapping[str, tuple[str, str]],
    catalog: BattleReportCatalog,
) -> dict[str, Any]:
    return {
        "title": title,
        "round_turn_label": label,
        "facts": [],
        "participants": _participant_records(participants, visuals, state, team_of, catalog),
    }


def _state_changes(
    participants: Sequence[Mapping[str, Any]],
    before: Mapping[str, Mapping[str, Any]],
    after: Mapping[str, Mapping[str, Any]],
    catalog: BattleReportCatalog,
) -> list[dict[str, str]]:
    changes = []
    for participant in participants:
        key = participant["id"]
        for resource_id, definition in catalog.resources.items():
            label = str(definition["label"])
            old = before[key]["resources"][resource_id]["current"]
            new = after[key]["resources"][resource_id]["current"]
            if abs(new - old) < 0.0005:
                continue
            delta = new - old
            changes.append(
                {
                    "tone": "positive" if delta > 0 else "negative",
                    "text": f"{participant['name']} 的{label} {_number(old)} → {_number(new)}（{delta:+.2f}）",
                }
            )
        old_statuses = set(before[key]["statuses"])
        new_statuses = set(after[key]["statuses"])
        for name in sorted(new_statuses - old_statuses):
            changes.append({"tone": "negative", "text": f"{participant['name']} 获得 {name}"})
        for name in sorted(old_statuses - new_statuses):
            changes.append({"tone": "positive", "text": f"{participant['name']} 的 {name} 结束"})
    return changes


def _fact(label: str, value: Any) -> dict[str, Any]:
    return {"label": label, "value": value, "display": _number(value) if isinstance(value, int | float) else str(value)}


def _status_display(value: Mapping[str, Any]) -> str:
    parts = []
    if int(value.get("stacks") or 1) > 1:
        parts.append(f"{int(value['stacks'])} 层")
    parts.append(f"剩余 {int(value.get('turns') or 0)} 回合")
    if value.get("source"):
        parts.append(f"来源 {value['source']}")
    return " · ".join(parts)


def _number(value: Any) -> str:
    number = round(float(value or 0), 2)
    return str(int(number)) if number.is_integer() else f"{number:.2f}".rstrip("0").rstrip(".")


def _time_label(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.strftime("%Y年%m月%d日 %H:%M:%S")
