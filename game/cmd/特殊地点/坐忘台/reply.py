"""坐忘台命令回复构造。"""

from __future__ import annotations

from game.features.yijing import YijingFeature, YijingRefundResult
from message import DocumentMessage, M

from ...presentation import error_document


def refund_result(feature: YijingFeature, value: YijingRefundResult) -> DocumentMessage:
    """坐忘成功的回复：退点前练到几阶、道行从多少退回多少。"""

    builder = M.document()
    builder.section(value.name, icon="game.seed")
    builder.line(
        M.status("坐忘完成", tone="positive"),
        " ",
        feature.copy(
            "结算",
            "完成",
            {
                "人物": value.name,
                "丹药": value.medicine,
                "退点": value.before,
                "退回": value.points_after,
            },
        ),
    )
    builder.row(("道行", f"{value.points_before} → {value.points_after}"))
    return builder.build()


def refund_error(feature: YijingFeature, message: str) -> DocumentMessage:
    """被拒的回复（理由用特性给出的原文）。"""

    return error_document(
        feature.copy("错误", "标题"), "game.pin_doc", "坐忘失败", message, tone="danger"
    )
