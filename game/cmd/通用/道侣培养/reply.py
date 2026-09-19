"""道侣培养回复构造。"""

from __future__ import annotations

from game.features.daolv_peiyang import (
    CompanionBreakthroughResult,
    CompanionCultivationFeature,
    CompanionCultivationView,
    CompanionLawResult,
)
from message import M


def view(feature: CompanionCultivationFeature, result: CompanionCultivationView):
    definition = result.definition
    instance = result.instance
    title = feature.copy("道侣", "标题").format_map({"名称": definition.name})
    builder = (
        M.document()
        .header(title)
        .section("修为", icon="status")
        .row(
            (feature.copy("道侣", "境界"), result.realm_name),
            (feature.copy("道侣", "等级"), instance.level),
        )
        .field(
            feature.copy("道侣", "经验"),
            _progress(instance.experience, result.next_experience),
        )
        .section(feature.copy("道侣", "修行构筑"), icon="skill")
    )
    for category, names in result.cultivation_names:
        builder.field(category, "、".join(names))
    builder.section(feature.copy("道侣", "本命武器"), icon="weapon")
    builder.field("名称", instance.weapon_name)
    builder.row(("器阶", result.weapon_stage), ("等级", instance.weapon_level))
    builder.field(
        "器律孔",
        f"{sum(law is not None for law in instance.weapon_laws)}/{result.open_law_slots}",
    )
    builder.field(
        "经验",
        _progress(
            instance.weapon_experience,
            result.weapon_next_experience,
            tone="emphasis",
        ),
    )
    for slot, law_name in result.weapon_law_names:
        builder.item(slot, law_name)
    return builder.build()


def breakthrough(
    feature: CompanionCultivationFeature, result: CompanionBreakthroughResult
):
    text = feature.copy("突破", "道侣成功").format_map(
        {"名称": result.view.definition.name, "丹药": result.medicine_name, "境界": result.view.realm_name},
    )
    return (
        M.document()
        .section("道侣突破", icon="status")
        .line(M.status("突破完成", tone="positive"), " ", text)
        .build()
    )


def forged(feature: CompanionCultivationFeature, result: CompanionLawResult):
    text = feature.copy("覆炼", "道侣成功").format_map(
        {"名称": result.view.definition.name, "器律": result.law_name, "孔位": result.slot}
    )
    return (
        M.document()
        .section("道侣覆炼", icon="weapon")
        .line(M.status("覆炼完成", tone="positive"), " ", text)
        .build()
    )


def error(message: str):
    return (
        M.document()
        .section("道侣培养", icon="notice")
        .line(M.status("培养失败", tone="danger"), " ", message)
        .build()
    )


def _progress(current: int, required: int, *, tone: str = "cultivation"):
    if required <= 0:
        return M.status("圆满", tone="mystic")
    return M.progress(current, required, tone=tone, display="both")


__all__ = ["breakthrough", "error", "forged", "view"]
