"""服丹命令回复构造。"""

from __future__ import annotations

from ...actions import CommandAction
from ...presentation import error_document

from game.features.fudan import MedicineFeature, AutoMedicineResult

from typing import Sequence

from message import DocumentMessage, M


def setting(feature: MedicineFeature, result: AutoMedicineResult) -> DocumentMessage:
    line = feature.copy(
        "自动用药",
        result.target, {"道侣": result.target_name, "状态": "开启" if result.enabled else "关闭"},
    )
    return (
        M.document()
        .section(feature.copy("自动用药", "标题"), icon="game.seed")
        .line(
            # 状态那行做成**分支按钮**：按这次设置的主体给分支（人药/侣药），点了回二选一菜单，只填入。
            M.command(
                "已开启" if result.enabled else "已关闭",
                (
                    ("侣药 开|侣药 关" if result.target == "道侣" else "人药 开|人药 关")
                ),
            )
        )
        .line(line)
        .build()
    )


def error(
    feature: MedicineFeature, message: str, actions: Sequence[CommandAction] = ()
) -> DocumentMessage:
    """失败回执：标题与状态词都取自展示数据集，动作由玩法层给。"""

    return error_document(
        feature.copy("错误", "标题"),
        "game.pin_doc",
        feature.copy("错误", "失败"),
        message,
        tone="danger",
        actions=actions,
        hint=feature.copy("错误", "格式"),
    )


__all__ = ["error", "setting"]
