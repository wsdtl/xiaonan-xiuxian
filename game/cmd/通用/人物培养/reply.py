"""人物培养回复构造。"""

from __future__ import annotations


from ...actions import CommandAction
from ...presentation import candidate_lines, error_document

from typing import Sequence

from game.features.renwu_peiyang import (
    BreakthroughOffer,
    CharacterCultivationFeature,
    CharacterBreakthroughResult,
    CharacterCultivationView,
    CharacterEquipResult,
    CharacterLawResult,
)

from message import Status, Progress, DocumentMessage, M


def _render_candidates(
    feature: CharacterCultivationFeature,
    builder: object,
    offer: BreakthroughOffer | None,
    *,
    title_key: str,
) -> bool:
    """把「本境界全部可用突破丹」铺进卡片——查看页与失败卡共用这一段，只有文案键不同。

    丹名是无边框按钮：名字只作显示、句柄一律用编号（`查看 <编号>`）。
    放在 `line` 的槽位而不是 `field` 的标签位——后者会把 CommandLink 打回 repr。
    """

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


def view(feature: CharacterCultivationFeature, result: CharacterCultivationView) -> DocumentMessage:
    profile = result.profile
    builder = (
        M.document()

        .inline_section(
            "修为",
            M.text(f"{profile.realm_name}{profile.level}级 · 经验")
            + (_progress(profile.experience, result.next_experience),),
            icon="status",
        )
    )
    _render_candidates(feature, builder, result.breakthrough, title_key="可突破标题")
    builder.section(feature.copy("人物", "修行构筑"), icon="skill")
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
                + (M.command(value.name, f"查看 {value.name}"),),
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
        builder.item(law.slot, M.command(law.name, f"查看 {law.name}"))
    return builder.build()


def equipped(feature: CharacterCultivationFeature, result: CharacterEquipResult) -> DocumentMessage:
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
) -> DocumentMessage:
    text = feature.copy("突破", "人物成功").format_map(
        {
            "品级": result.medicine_grade,
            "丹药": result.medicine_name,
            "境界": result.realm_name,
        }
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


def forged(feature: CharacterCultivationFeature, result: CharacterLawResult) -> DocumentMessage:
    text = feature.copy("覆炼", "人物成功").format_map(
        {"器律": result.law_name, "孔位": result.slot}
    )
    return (
        M.document()
        .section("人物覆炼", icon="weapon")
        .line(M.status("覆炼完成", tone="positive"), " ", text)
        .build()
    )


def error(
    feature: CharacterCultivationFeature,
    message: str,
    actions: Sequence[CommandAction] = (),
    offer: BreakthroughOffer | None = None,
) -> DocumentMessage:
    """失败回执：标题与状态词取自展示数据集，动作由玩法层给。

    突破失败时顺带把本境界**全部**候选丹列出来（`offer` 由命令层算好传进来）——
    名字写错的人不用猜，照着点就行。
    """

    def add_candidates(builder: object) -> None:
        _render_candidates(feature, builder, offer, title_key="失败候选")

    return error_document(
        feature.copy("错误", "标题"),
        "notice",
        feature.copy("错误", "失败"),
        message,
        tone="danger",
        actions=actions,
        hint=feature.copy("错误", "格式"),
        render=add_candidates if offer is not None else None,
    )


def _progress(current: int, required: int, *, tone: str = "cultivation") -> Status | Progress:
    if required <= 0:
        return M.status("圆满", tone="mystic")
    return M.progress(current, required, tone=tone, display="both")


__all__ = ["breakthrough", "equipped", "error", "forged", "view"]
