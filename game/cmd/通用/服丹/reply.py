"""服丹命令回复构造。"""

from __future__ import annotations

from game.features.fudan import MedicineFeature, AutoMedicineResult, MedicineUseResult

from message import DocumentMessage, M


def used(feature: MedicineFeature, result: MedicineUseResult) -> DocumentMessage:
    key = f"{result.target}{'恢复' if result.effect == '恢复' else '寄存'}"
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


def error(message: str) -> DocumentMessage:
    return (
        M.document()
        .section("服丹", icon="notice")
        .line(M.status("服丹失败", tone="danger"), " ", message)
        .build()
    )


def _number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(round(value, 4))


__all__ = ["error", "setting", "used"]
