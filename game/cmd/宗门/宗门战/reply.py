"""宗门战命令回复构造。"""

from __future__ import annotations

from ...actions import CommandAction

from ...presentation import duration, error_document

from datetime import UTC, datetime
from typing import Sequence

from game.features.zhanbao import MyReportPage
from game.features.zongmen_zhan import SectWarFeature, SectWarHistoryPage, SectWarView
from launch.paths import public_url
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
    if value.report_id:
        builder.field(
            feature.text("查看", "战报"), M.link("打开战报", public_url("battle", value.report_id))
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


def recent_reports(feature: SectWarFeature, page: MyReportPage) -> DocumentMessage:
    """最近**尚未过期**的宗门战报：倒序、每条一个打开链接、末行页码。

    与「战报」组件的「我的战报」同款——数据同出一处（非资产战报库），只是这里只留宗门战。
    """

    builder = M.document().section(
        feature.text("查看", "记录标题"), icon="game.swords"
    )
    if not page.entries:
        builder.line(
            M.status("空", tone="muted"), " ", feature.text("结果", "最近为空")
        )
        return builder.build()
    builder.field(
        feature.text("查看", "总数"),
        feature.text("查看", "最近总数", {"数量": page.total}),
    )
    for entry in page.entries:
        builder.line(
            entry.finished_at,
            M.link(
                feature.text("查看", "打开战报"),
                public_url("battle", entry.report_id),
            ),
        )
    if page.total > max(1, page.size):
        page_size = max(1, page.size)
        builder.small(
            feature.text(
                "格式", "页码", {"当前页": page.page, "总页数": max(1, (page.total + page_size - 1) // page_size)}
            )
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
