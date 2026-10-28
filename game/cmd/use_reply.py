"""使用物品的公共回执：装配、覆炼、灵宝、服丹。"""
from __future__ import annotations

from game.features.buzhen import FormationArmResult
from game.features.daolv_peiyang import CompanionLawResult
from game.features.fudan import MedicineFeature, MedicineUseResult
from game.features.renwu_peiyang import (
    CharacterCultivationFeature,
    CharacterEquipResult,
    CharacterLawResult,
)
from game.features.xiantian_lingbao import (
    InnateTreasureEquipResult,
    InnateTreasureFeature,
)
from message import DocumentMessage, M

from .presentation import linked_name_line

_USE_KEYS = {
    ("人物", "恢复"): "人物恢复",
    ("道侣", "恢复"): "道侣恢复",
    ("人物", "寄存"): "人物寄存",
    ("道侣", "寄存"): "道侣寄存",
}


def equipped(
    feature: CharacterCultivationFeature, result: CharacterEquipResult
) -> DocumentMessage:
    text = feature.copy("装配", "人物成功").format_map(
        {"名称": result.content_name, "类别": result.category, "槽位": result.slot}
    )
    builder = (
        M.document()
        .section("装配", icon="game.gear")
        .line(M.status("装配完成", tone="positive"), " ", text)
    )
    if result.treasure_activation is not None:
        activation = result.treasure_activation
        builder.section("灵宝", icon="game.amulet").field(
            activation.name, activation.summary
        )
    return builder.build()


def forged(
    feature: CharacterCultivationFeature, result: CharacterLawResult
) -> DocumentMessage:
    text = feature.copy("覆炼", "人物成功").format_map(
        {"器律": result.law_name, "孔位": result.slot}
    )
    return (
        M.document()
        .section("覆炼", icon="game.hammer")
        .line(M.status("覆炼完成", tone="positive"), " ", text)
        .build()
    )


def law(feature: object, result: object) -> DocumentMessage:
    if isinstance(result, CompanionLawResult):
        view = result.view
        text = feature.copy("覆炼", "道侣成功").format_map(
            {
                "名称": view.definition.name,
                "器律": result.law_name,
                "孔位": result.slot,
            }
        )
    else:
        text = feature.copy("覆炼", "人物成功").format_map(
            {"器律": result.law_name, "孔位": result.slot}
        )
    return (
        M.document()
        .section("覆炼", icon="game.hammer")
        .line(M.status("覆炼完成", tone="positive"), " ", text)
        .build()
    )


def treasure(
    feature: InnateTreasureFeature, result: InnateTreasureEquipResult
) -> DocumentMessage:
    value = result.treasure
    return (
        M.document()
        .section(feature.copy("标题"), icon="game.manual")
        .line(
            M.status("执掌完成", tone="positive"),
            " ",
            *linked_name_line(
                feature.copy(
                    "执掌成功", {"名称": "\u0000", "权柄": value.authority}
                ),
                value.name,
            ),
        )
        .field(feature.copy("效果"), f"{value.effect.node}：{value.effect.ability}")
        .build()
    )


def formation(feature: object, result: FormationArmResult) -> DocumentMessage:
    copy = feature.copy()
    prepared = result.prepared
    text = copy.text["布阵"]
    builder = (
        M.document()
        .section(f"{prepared.grade_name}{prepared.name}", icon="game.swords")
        .line(M.status("阵法入槽", tone="positive"))
        .line(text["过程"])
        .field(text["结果"], "下一场正式战斗")
    )
    if prepared.treasure_line:
        builder = builder.field(text["灵宝"], prepared.treasure_line)
    return builder.small(text["话语"]).build()


def medicine(
    feature: MedicineFeature, result: MedicineUseResult
) -> DocumentMessage:
    key = _USE_KEYS[(result.target, result.effect)]
    line = feature.copy(
        "服丹",
        key,
        {
            "人物": result.target_name,
            "道侣": result.target_name,
            "品级": result.grade_name,
            "丹药": result.medicine_name,
            "资源": result.resource,
            "实际恢复": _number(result.recovered),
        },
    )
    builder = (
        M.document().section(feature.copy("服丹", "标题"), icon="game.seed").line(line)
    )
    if result.treasure_activation is not None:
        activation = result.treasure_activation
        builder.section("灵宝", icon="game.box").field(
            activation.name, activation.summary
        )
    return builder.build()


def _number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(round(value, 4))


RENDERERS = {
    "equip": equipped,
    "forge": forged,
    "law": law,
    "treasure": treasure,
    "medicine": medicine,
    "formation": formation,
}


__all__ = ["RENDERERS", "equipped", "forged", "formation", "law", "medicine", "treasure"]
