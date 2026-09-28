"""讨伐命令回复构造。"""

from __future__ import annotations

from game.features.taofa import RaidFeature, RaidProgress, RaidSettlement, RaidStarted
from message import DocumentMessage, M

from ...presentation import duration, natural_deadline, sentence


def started(feature: RaidFeature, value: RaidStarted) -> DocumentMessage:
    return (
        M.document()
        .header(feature.text("开始", "标题"))
        .inline_section("讨伐状态", M.status("进行中", tone="danger"), icon="combat")
        .section(value.location_name, icon="status")
        .row(
            (feature.text("开始", "参与用户"), value.participant_count),
            (feature.text("开始", "敌方编组"), value.enemy_group_count),
        )
        .field(feature.text("开始", "结束时间"), natural_deadline(value.ends_at))
        .small(feature.text("开始", "说明"))
        .build()
    )


def progress(feature: RaidFeature, value: RaidProgress) -> DocumentMessage:
    return (
        M.document()
        .header(feature.text("进度", "标题"))
        .inline_section(
            "讨伐状态",
            M.status(
                "可结算" if value.ended else "进行中",
                tone="positive" if value.ended else "danger",
            ),
            icon="combat",
        )
        .section(value.location_name, icon="status")
        .field(feature.text("进度", "剩余时间"), duration(value.remaining_seconds))
        .field(
            feature.text("进度", "首领血段"),
            M.progress(
                value.boss_phase, value.boss_phases, tone="danger", display="value"
            ),
        )
        .small(
            feature.text("进度", "已结束")
            if value.ended
            else feature.text("进度", "进行中")
        )
        .build()
    )


def settlement(feature: RaidFeature, value: RaidSettlement) -> DocumentMessage:
    won = value.winner == "left"
    result = feature.result_label(value.winner)
    return (
        M.document()
        .header(feature.text("结算", "标题"))
        .inline_section(
            "讨伐结果",
            M.status(result, tone="positive" if won else "danger"),
            icon="combat",
        )
        .section(value.location_name, icon="status")
        .field(feature.text("结算", "战败敌人"), value.defeated_enemies)
        .small(feature.reward_note(value.winner))
        .build()
    )


def error(feature: RaidFeature, message: str) -> DocumentMessage:
    return (
        M.document()
        .section(feature.text("错误", "标题"), icon="notice")
        .line(M.status("讨伐失败", tone="danger"), " ", sentence(message))
        .build()
    )


__all__ = ["error", "progress", "settlement", "started"]
