"""赠送命令回复构造。"""

from __future__ import annotations

from ...actions import CommandAction
from ...presentation import error_document

from message import DocumentBuilder, DocumentMessage, M

from typing import Sequence

from game.features.zengsong import GiftFeature, GiftResult

from ...presentation import sentence


def stones(feature: GiftFeature, target_name: str, value: GiftResult) -> DocumentMessage:
    return (
        _result(feature, target_name)
        .field("灵石", M.text(value.quantity, tone="cultivation"))
        .build()
    )


def item(
    feature: GiftFeature,
    target_name: str,
    value: GiftResult,
    *,
    grade_name: str,
    item_name: str,
) -> DocumentMessage:
    return (
        _result(feature, target_name)
        .field(
            "基础物品",
            M.command(
                M.text(f"{grade_name}{item_name}"),
                f"查看 {item_name}",
            ),
        )
        .field("数量", value.quantity)
        .build()
    )


def error(
    feature: GiftFeature, message: str, actions: Sequence[CommandAction] = ()
) -> DocumentMessage:
    # 形状统一走 error_document（game/cmd/presentation.py），行为与原来一致。
    return error_document(        feature.text("错误", "标题"), "game.pin_doc", "赠送失败", sentence(message), tone="danger",
        actions=actions,
    )


def _result(feature: GiftFeature, target_name: str) -> DocumentBuilder:
    return (
        M.document()

        .inline_section("赠礼", M.status("完成", tone="positive"), icon="game.success")
        .section("去向", icon="game.role")
        .field("接收者", M.command(target_name, f"查看 {target_name}"))
    )


__all__ = ["error", "item", "stones"]
