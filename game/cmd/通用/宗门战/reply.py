"""宗门战命令回复构造。"""

from __future__ import annotations

from game.features.zongmen_zhan import SectWarFeature, SectWarHistoryPage, SectWarView
from message import DocumentMessage, M

from ...actions import message_actions


def view(feature: SectWarFeature, value: SectWarView) -> DocumentMessage:
    status = feature.text("状态", value.status)
    builder = (
        M.document()
        .header(feature.text("查看", "标题"))
        .inline_section(
            "宗门战状态",
            M.status(status, tone=_status_tone(value.status)),
            icon="combat",
        )
        .section("对阵双方", icon="player")
        .field(
            feature.text("查看", "双方"),
            feature.text(
                "格式", "双方", {"甲": value.attacker_name, "乙": value.defender_name}
            ),
        )
        .row(
            (value.attacker_name, value.attacker_count),
            (value.defender_name, value.defender_count),
        )
        .field(
            feature.text("查看", "押注"),
            M.text(value.wager, tone="cultivation"),
        )
        .row(
            (
                "攻方锁阵",
                M.status(
                    "已锁定" if value.attacker_locked else "未锁定",
                    tone="positive" if value.attacker_locked else "muted",
                ),
            ),
            (
                "守方锁阵",
                M.status(
                    "已锁定" if value.defender_locked else "未锁定",
                    tone="positive" if value.defender_locked else "muted",
                ),
            ),
        )
    )
    if value.attacker_formation or value.defender_formation:
        builder.section("双方阵法", icon="item").row(
            ("攻方阵法", value.attacker_formation or "无"),
            ("守方阵法", value.defender_formation or "无"),
        )
    if value.winner:
        builder.field(
            feature.text("查看", "胜负"),
            M.text(_winner(feature, value), tone="positive"),
        )
    if value.report_id:
        builder.field(
            feature.text("查看", "战报"), M.text(value.report_id, tone="muted")
        )
    return builder.actions(message_actions(feature.actions(value.status))).build()


def history(feature: SectWarFeature, value: SectWarHistoryPage) -> DocumentMessage:
    builder = (
        M.document()
        .header(feature.text("查看", "记录标题"))
        .section("历史战录", icon="combat")
        .field(feature.text("查看", "总数"), value.total)
    )
    if not value.entries:
        builder.line(
            M.status("空", tone="muted"), " ", feature.text("结果", "记录为空")
        )
    for index, entry in enumerate(value.entries, start=1):
        builder.item(
            index,
            feature.text(
                "格式",
                "记录", {"甲": entry.attacker_name, "乙": entry.defender_name, "状态": feature.text("状态", entry.status)},
            ),
        ).line(
            feature.text("查看", "战书"),
            "：",
            M.command(M.text(entry.war_id), f"战况 {entry.war_id}"),
        )
    return builder.small(
        feature.text("格式", "页码", {"当前页": value.page, "总页数": value.page_count})
    ).build()


def error(message: str) -> DocumentMessage:
    return (
        M.document()
        .section("宗门战", icon="notice")
        .line(M.status("操作失败", tone="danger"), " ", message)
        .build()
    )


def _winner(feature: SectWarFeature, value: SectWarView) -> str:
    if value.winner == "left":
        return value.attacker_name
    if value.winner == "right":
        return value.defender_name
    return feature.text("结果", "平局")


def _status_tone(status: str) -> str:
    if status in {"completed", "settled"}:
        return "positive"
    if status in {"cancelled", "rejected", "expired"}:
        return "muted"
    if status in {"fighting", "started"}:
        return "danger"
    return "warning"


__all__ = ["error", "history", "view"]
