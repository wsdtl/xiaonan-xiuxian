"""通过公共接口验收战斗结算、战场、阵法、丹药和战报的一致性。"""

from __future__ import annotations

import asyncio
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.combat import (
    CombatantReportSpec,
    CombatantSpec,
    CombatBuildRef,
    CombatFieldSpec,
    CombatFormationSpec,
    CombatMedicineSpec,
    CombatReportSpec,
    CombatRequest,
)
from game.core.data import JsonDataService
from tools.combat_support import isolated_combat_service


def _build(content_ids: tuple[str, str, str, str]) -> tuple[CombatBuildRef, ...]:
    sections = ("功法", "真意", "气机", "器律")
    return tuple(
        CombatBuildRef(
            section=section,
            content_id=content_id,
            born_order=index + 1,
        )
        for index, (section, content_id) in enumerate(zip(sections, content_ids))
    )


def _fighter(
    combatant_id: str,
    name: str,
    gender: str,
    build: tuple[str, str, str, str],
    speed: int,
) -> CombatantSpec:
    return CombatantSpec(
        id=combatant_id,
        name=name,
        combatant_type="修士",
        gender=gender,
        level=30,
        attributes={
            "血气上限": 5000,
            "精神上限": 800,
            "护盾上限": 500,
            "攻击": 620,
            "防御": 120,
            "速度": speed,
            "命中率": 100,
            "暴击率": 25,
            "格挡率": 15,
            "格挡减伤": 30,
        },
        weapon_attack=240,
        build=_build(build),
        inventory={"验收回血丹:01": 3, "验收回神丹:01": 3},
        inventory_owner_id=combatant_id,
        auto_medicine=True,
        medicine_threshold=0.8,
    )


def _request() -> CombatRequest:
    left = (
        _fighter("L1", "青玄", "男", ("400541", "410105", "420006", "700033"), 130),
        _fighter("L2", "素心", "女", ("400542", "410106", "420007", "700034"), 112),
    )
    right = (
        _fighter("R1", "赤羽", "女", ("400543", "410107", "420208", "700035"), 126),
        _fighter("R2", "玄岳", "男", ("400544", "410108", "420222", "700036"), 108),
    )
    participants = tuple(
        CombatantReportSpec(id=value.id, title="验收参战者")
        for value in (*left, *right)
    )
    return CombatRequest(
        left_team=left,
        right_team=right,
        seed=20260806,
        action_limit=50,
        medicine_definitions=(
            CombatMedicineSpec("验收回血丹:01", "验收回血丹", "01", "血气", 25),
            CombatMedicineSpec("验收回神丹:01", "验收回神丹", "01", "精神", 25),
        ),
        medicine_selection_strategy="缺口优先",
        report=CombatReportSpec(
            participants=participants,
            scene="丘陵验收场",
            generated_at="2026-08-06T12:00:00+08:00",
            include_presentation=True,
        ),
        field=CombatFieldSpec(
            "610033",
            "丘陵验收场",
            "地表",
            (12, 34),
            1880,
            "丘陵",
        ),
        left_formation=CombatFormationSpec("530001", "黄", 1),
        right_formation=CombatFormationSpec("530002", "黄", 2),
    )


def _assert_report(result) -> None:
    report = result.report
    presentation = result.presentation
    assert report is not None and presentation is not None
    assert len(report["events"]) == len(result.events)
    assert report["result"]["event_count"] == len(result.events)
    assert report["field"]["stage_changes"]
    assert len(report["formations"]) == 2
    assert all(value["rotations"] > 0 for value in report["formations"])

    categories = Counter(value["category"] for value in report["events"])
    assert all(categories[name] > 0 for name in ("action", "damage", "status", "recover"))
    assert all(value["kind_label"] for value in report["events"])

    participant_reports = {value["id"]: value for value in report["participants"]}
    for participant in (*result.left_results, *result.right_results):
        raw_damage = sum(
            event.amount
            for event in result.events
            if event.kind == "造成伤害后" and event.source_id == participant.id
        )
        reported_damage = float(participant_reports[participant.id]["totals"][0]["value"])
        assert math.isclose(raw_damage, reported_damage, abs_tol=0.011)
        sections = {
            value["section"] for value in participant_reports[participant.id]["techniques"]
        }
        assert sections == {"功法", "真意", "气机", "器律"}

    medicine_events = [event for event in result.events if event.kind == "使用丹药后"]
    consumed = sum(
        sum(value.consumed_items.values())
        for value in (*result.left_results, *result.right_results)
    )
    assert medicine_events and len(medicine_events) == consumed
    assert all(event.values.get("丹药编号") for event in medicine_events)

    formation_events = [
        value for value in report["events"] if value["kind"] == "阵法冲击后"
    ]
    assert formation_events
    assert all(str(value["source"]["id"]).startswith("阵法:") for value in formation_events)

    main, bundle = presentation
    assert main["version"] == 4
    assert main["document_title"].startswith("晓楠修仙 · ")
    assert main["time_label"] == "2026年08月06日 12:00:00"
    assert main["ui"]["defaults"] == {
        "mode": "compact",
        "filter": "all",
        "snapshot": "after",
    }
    assert "raw" not in bundle
    assert len(main["formations"]) == 2
    assert any("左阵:" in value for value in main["summary"]["lines"])
    assert any("右阵:" in value for value in main["summary"]["lines"])
    filters = bundle["events"]["0"]["filters"]
    filter_counts = {value["id"]: value["count"] for value in filters}
    assert filter_counts["all"] == len(result.events)
    assert sum(value for key, value in filter_counts.items() if key != "all") == len(
        result.events
    )

    last_transition = next(reversed(bundle["transitions"].values()))
    replayed = {
        value["key"]: {gauge["id"]: gauge["current"] for gauge in value["gauges"]}
        for value in last_transition["comparison"]["after"]["participants"]
    }
    for participant in (*result.left_results, *result.right_results):
        assert math.isclose(replayed[participant.id]["health"], participant.health, abs_tol=0.001)
        assert math.isclose(replayed[participant.id]["spirit"], participant.spirit, abs_tol=0.001)
        assert math.isclose(replayed[participant.id]["shield"], participant.shield, abs_tol=0.001)

    titles = [value["title"] for value in bundle["events"]["0"]["timeline"]]
    assert all("造成伤害后" not in value and "技能施放后" not in value for value in titles)


def main() -> None:
    data = JsonDataService(ROOT / "data")
    data.initialize()
    with isolated_combat_service(data) as combat:
        status = combat.status()
        result = asyncio.run(combat.execute(_request()))
    _assert_report(result)
    categories = Counter(value["category"] for value in result.report["events"])
    print(
        "战斗核心与战报验收通过："
        f"{status.event_count} 个事件定义，{result.actions} 次行动，"
        f"{len(result.events)} 条事件，分类 {dict(categories)}，"
        f"地势 {result.field.stage_name}，阵法 {len(result.formations)} 座。"
    )


if __name__ == "__main__":
    main()
