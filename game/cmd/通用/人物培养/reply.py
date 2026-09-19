"""人物培养回复构造。"""

from __future__ import annotations

from game.features.renwu_peiyang import (
    CharacterBreakthroughResult,
    CharacterCultivationFeature,
    CharacterCultivationView,
    CharacterEquipResult,
    CharacterLawResult,
)
from message import M


def view(feature: CharacterCultivationFeature, result: CharacterCultivationView):
    profile = result.profile
    builder = (
        M.document()
        .header(f"{profile.name} · {feature.copy('人物', '标题')}")
        .inline_section(
            "修为",
            M.text(f"{profile.realm_name}{profile.level}级 · 经验")
            + (_progress(profile.experience, result.next_experience),),
            icon="status",
        )
        .section(feature.copy("人物", "修行构筑"), icon="skill")
    )
    equipped = {
        (entry.category, entry.slot): entry for entry in profile.equipped_content
    }
    for category, total in profile.cultivation_slots:
        values = [
            equipped[(category, slot)]
            for slot in range(1, total + 1)
            if (category, slot) in equipped
        ]
        builder.field(
            category, f"{len(values)}/{total}" + ("" if values else " · 尚未装配")
        )
        for value in values:
            builder.field(
                f"{category}{value.slot}",
                M.text(f"{value.grade_name} · " if value.grade_name else "")
                + (M.command(value.name, f"查看 {value.content_id}"),),
            )
    weapon = profile.weapon
    builder.section(feature.copy("人物", "本命武器"), icon="weapon")
    builder.row(("名称", weapon.name), ("器阶", weapon.stage))
    builder.row(
        ("等级", weapon.level),
        ("器律孔", f"{len(weapon.equipped_laws)}/{weapon.open_law_slots}"),
    )
    builder.field(
        "经验",
        _progress(weapon.experience, result.weapon_next_experience, tone="emphasis"),
    )
    for law in weapon.equipped_laws:
        builder.item(law.slot, M.command(law.name, f"查看 {law.content_id}"))
    return builder.build()


def equipped(feature: CharacterCultivationFeature, result: CharacterEquipResult):
    text = feature.copy("装配", "人物成功").format_map(
        {"名称": result.content_name, "类别": result.category, "槽位": result.slot}
    )
    builder = (
        M.document()
        .section("人物装配", icon="skill")
        .line(M.status("装配完成", tone="positive"), " ", text)
    )
    if result.treasure_activation is not None:
        activation = result.treasure_activation
        builder.section("先天灵宝", icon="item").field(
            activation.name, activation.summary
        )
    return builder.build()


def breakthrough(
    feature: CharacterCultivationFeature, result: CharacterBreakthroughResult
):
    text = feature.copy("突破", "人物成功").format_map(
        {"丹药": result.medicine_name, "境界": result.realm_name}
    )
    builder = (
        M.document()
        .section("人物突破", icon="status")
        .line(M.status("突破完成", tone="positive"), " ", text)
    )
    if result.treasure_activation is not None:
        activation = result.treasure_activation
        builder.section("先天灵宝", icon="item").field(
            activation.name, activation.summary
        )
    return builder.build()


def forged(feature: CharacterCultivationFeature, result: CharacterLawResult):
    text = feature.copy("覆炼", "人物成功").format_map(
        {"器律": result.law_name, "孔位": result.slot}
    )
    return (
        M.document()
        .section("人物覆炼", icon="weapon")
        .line(M.status("覆炼完成", tone="positive"), " ", text)
        .build()
    )


def error(message: str):
    return (
        M.document()
        .section("人物培养", icon="notice")
        .line(M.status("培养失败", tone="danger"), " ", message)
        .build()
    )


def _progress(current: int, required: int, *, tone: str = "cultivation"):
    if required <= 0:
        return M.status("圆满", tone="mystic")
    return M.progress(current, required, tone=tone, display="both")


__all__ = ["breakthrough", "equipped", "error", "forged", "view"]
