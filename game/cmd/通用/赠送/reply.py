"""赠送命令回复构造。"""

from __future__ import annotations

from message import DocumentBuilder, DocumentMessage, M

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
                M.text(f"{grade_name}{item_name}", tone="emphasis"),
                f"查看 {value.item_id}",
            ),
        )
        .field("数量", value.quantity)
        .build()
    )


def error(feature: GiftFeature, message: str) -> DocumentMessage:
    return (
        M.document()
        .section(feature.text("错误", "标题"), icon="notice")
        .line(M.status("赠送失败", tone="danger"), " ", sentence(message))
        .build()
    )


def _result(feature: GiftFeature, target_name: str) -> DocumentBuilder:
    return (
        M.document()
        .header(feature.text("", "标题"))
        .inline_section("赠礼结果", M.status("完成", tone="positive"), icon="success")
        .section("赠礼去向", icon="player")
        .field("接收者", M.text(target_name, tone="emphasis"))
    )


__all__ = ["error", "item", "stones"]
