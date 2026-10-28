"""宗门战命令回复构造。"""

from __future__ import annotations

from ...actions import CommandAction

from ...presentation import duration, error_document

from datetime import UTC, datetime
from typing import Sequence

from game.features.zongmen_zhan import SectWarFeature, SectWarHistoryPage, SectWarView
from message import DocumentMessage, M

from ...actions import message_actions


def view(feature: SectWarFeature, value: SectWarView) -> DocumentMessage:
    status = feature.text("状态", value.status)
    builder = (
        M.document()

        .inline_section(
            "状态",
            M.status(status, tone=_status_tone(value.status)),
            icon="game.swords",
        )
        .section("对阵", icon="game.role")
        .field(
            feature.text("查看", "双方"),
            feature.text(
                "格式", "双方", {"甲": value.attacker_name, "乙": value.defender_name}
            ),
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
    if value.attacker_count or value.defender_count:
        builder.row(
            (value.attacker_name, value.attacker_count),
            (value.defender_name, value.defender_count),
        )
    if value.status == "战斗中" and value.ends_at is not None:
        # 细节：别的活动卡片都印剩余时间，宗门战也得印——不然玩家不知道要等多久。
        builder.field(
            feature.text("查看", "剩余时间"),
            duration(max(0, int((value.ends_at - datetime.now(UTC)).total_seconds()))),
        )
    if value.winner:
        builder.field(
            feature.text("查看", "胜负"),
            M.text(_winner(feature, value), tone="positive"),
        )
    return builder.actions(message_actions(feature.actions(value.status))).build()


def history(feature: SectWarFeature, value: SectWarHistoryPage) -> DocumentMessage:
    builder = M.document().section(
        "战录", icon="game.swords"
    )
    # 总数为 0 时下面那句「记录为空」已经把同一件事说过了，不必再说一遍。
    if value.total:
        builder.field(feature.text("查看", "总数"), value.total)
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
            M.command(M.text(entry.war_id), f"宗门战况 {entry.war_id}"),
        )
    # 只有一页就不报页码。
    if value.page_count > 1:
        builder.small(
            feature.text("格式", "页码", {"当前页": value.page, "总页数": value.page_count})
        )
    return builder.build()


def error(
    feature: SectWarFeature, message: str, actions: Sequence[CommandAction] = ()
) -> DocumentMessage:
    """失败回执：标题与状态词取自展示数据集，动作由玩法层给。"""

    return error_document(
        feature.text("错误", "标题"),
        "game.pin_doc",
        feature.text("错误", "失败"),
        message,
        tone="danger",
        actions=actions,
        hint=feature.text("错误", "格式"),
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
