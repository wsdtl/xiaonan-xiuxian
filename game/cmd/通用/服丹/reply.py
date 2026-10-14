"""服丹命令回复构造。"""

from __future__ import annotations

from ...actions import CommandAction
from ...presentation import error_document

from game.features.fudan import MedicineFeature, AutoMedicineResult, MedicineUseResult

from typing import Sequence

from message import DocumentMessage, M


#: 「人物／道侣」x「恢复／寄存」四种情形各自的展示键名。
_USE_KEYS = {
    ("人物", "恢复"): "人物恢复",
    ("道侣", "恢复"): "道侣恢复",
    ("人物", "寄存"): "人物寄存",
    ("道侣", "寄存"): "道侣寄存",
}

def used(feature: MedicineFeature, result: MedicineUseResult) -> DocumentMessage:
    # 键名写成字面量：拼出来的键名判据看不见（数据驱动判据要求每个展示键都有人读），
    # 而且写死了也更容易看出这四种情形各要一段文案。
    key = _USE_KEYS[(result.target, result.effect)]
    line = feature.copy(
        "服丹",
        key, {"人物": result.target_name, "道侣": result.target_name, "品级": result.grade_name, "丹药": result.medicine_name, "资源": result.resource, "实际恢复": _number(result.recovered)},
    )
    builder = (
        M.document().section(feature.copy("服丹", "标题"), icon="status").line(line)
    )
    if result.treasure_activation is not None:
        activation = result.treasure_activation
        builder.section("先天灵宝", icon="item").field(
            activation.name, activation.summary
        )
    return builder.build()


def setting(feature: MedicineFeature, result: AutoMedicineResult) -> DocumentMessage:
    line = feature.copy(
        "自动用药",
        result.target, {"道侣": result.target_name, "状态": "开启" if result.enabled else "关闭"},
    )
    return (
        M.document()
        .section(feature.copy("自动用药", "标题"), icon="status")
        .line(
            M.status(
                "已开启" if result.enabled else "已关闭",
                tone="positive" if result.enabled else "muted",
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
        "notice",
        feature.copy("错误", "失败"),
        message,
        tone="danger",
        actions=actions,
        hint=feature.copy("错误", "格式"),
    )


def _number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(round(value, 4))


__all__ = ["error", "setting", "used"]
