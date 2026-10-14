"""道侣培养回复构造。"""

from __future__ import annotations


from ...actions import CommandAction
from ...presentation import candidate_lines, error_document

from typing import Sequence

from game.features.daolv_peiyang import (
    CompanionBreakthroughOffer,
    CompanionCultivationFeature,
    CompanionBreakthroughResult,
    CompanionCultivationView,
    CompanionLawResult,
)

from message import Status, Progress, DocumentMessage, M


def _render_candidates(
    feature: CompanionCultivationFeature,
    builder: object,
    offer: CompanionBreakthroughOffer | None,
    *,
    title_key: str,
) -> bool:
    """把「本境界全部可用突破丹」铺进卡片——与人物培养共用同一段渲染。"""

    if offer is None or not offer.preview.can_breakthrough:
        return False
    if not offer.candidates:
        # 满级了、身上却没有对应突破丹：原先把整段掐掉，玩家看不出自己已经顶到头。
        # 用 inline_section：自带栏目、不会留下空栏目，也不需要额外开一个 section。
        builder.inline_section(
            feature.copy("突破", "缺丹").format_map(
                {"来源": offer.preview.realm_name, "目标": offer.preview.next_realm_name}
            ),
            icon="status",
        )
        return True
    preview = offer.preview
    candidate_lines(
        builder,
        title=feature.copy("突破", title_key).format_map(
            {"来源": preview.realm_name, "目标": preview.next_realm_name}
        ),
        entries=tuple(
            (
                candidate.name,
                f"查看 {candidate.medicine_id}",
                "、".join(f"{name}+{value}" for name, value in candidate.permanent)
                or feature.copy("突破", "无永久属性"),
            )
            for candidate in offer.candidates
        ),
        footer=feature.copy("突破", "候选共").format_map(
            {"数量": len(offer.candidates)}
        ),
    )
    return True


def view(feature: CompanionCultivationFeature, result: CompanionCultivationView) -> DocumentMessage:
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
    )
    _render_candidates(feature, builder, result.breakthrough, title_key="可突破标题")
    builder.section(feature.copy("道侣", "修行构筑"), icon="skill")
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
) -> DocumentMessage:
    text = feature.copy("突破", "道侣成功").format_map(
        {
            "名称": result.view.definition.name,
            "品级": result.medicine_grade,
            "丹药": result.medicine_name,
            "境界": result.view.realm_name,
        },
    )
    return (
        M.document()
        .section("道侣突破", icon="status")
        .line(M.status("突破完成", tone="positive"), " ", text)
        .build()
    )


def forged(feature: CompanionCultivationFeature, result: CompanionLawResult) -> DocumentMessage:
    text = feature.copy("覆炼", "道侣成功").format_map(
        {"名称": result.view.definition.name, "器律": result.law_name, "孔位": result.slot}
    )
    return (
        M.document()
        .section("道侣覆炼", icon="weapon")
        .line(M.status("覆炼完成", tone="positive"), " ", text)
        .build()
    )


def error(
    feature: CompanionCultivationFeature,
    message: str,
    actions: Sequence[CommandAction] = (),
    offer: CompanionBreakthroughOffer | None = None,
) -> DocumentMessage:
    """失败回执：标题与状态词取自展示数据集，动作由玩法层给。

    突破失败时顺带把本境界全部候选丹列出来（`offer` 由命令层算好传进来）。
    """

    def add_candidates(builder: object) -> None:
        _render_candidates(feature, builder, offer, title_key="失败候选")

    return error_document(
        feature.copy("道侣培养", "标题"),
        "notice",
        feature.copy("道侣培养", "失败"),
        message,
        tone="danger",
        actions=actions,
        render=add_candidates if offer is not None else None,
    )


def _progress(current: int, required: int, *, tone: str = "cultivation") -> Status | Progress:
    if required <= 0:
        return M.status("圆满", tone="mystic")
    return M.progress(current, required, tone=tone, display="both")


__all__ = ["breakthrough", "error", "forged", "view"]
