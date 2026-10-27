"""使用物品的公共回执：装配与覆炼成功页。"""
from __future__ import annotations

from game.features.renwu_peiyang import (
    CharacterCultivationFeature,
    CharacterEquipResult,
    CharacterLawResult,
)
from message import DocumentMessage, M


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


__all__ = ["equipped", "forged"]
