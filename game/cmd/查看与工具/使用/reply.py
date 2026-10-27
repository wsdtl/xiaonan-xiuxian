"""使用物品的错误回执与成功回执转发。"""
from __future__ import annotations

from game.features.renwu_peiyang import CharacterCultivationFeature
from message import DocumentMessage

from ...presentation import error_document
from ...use_reply import equipped, forged


def error(feature: CharacterCultivationFeature, message: str) -> DocumentMessage:
    return error_document(
        feature.copy("错误", "标题"),
        "game.pin_doc",
        feature.copy("错误", "失败"),
        message,
    )


__all__ = ["equipped", "error", "forged"]
