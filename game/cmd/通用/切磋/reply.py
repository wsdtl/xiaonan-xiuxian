"""切磋命令回复构造。"""

from __future__ import annotations

from game.features.qiecuo import DuelChallenge, DuelFeature, DuelResult
from launch.paths import public_url
from message import DocumentMessage, M

from ...presentation import natural_deadline, sentence


def challenge(feature: DuelFeature, value: DuelChallenge, target_name: str) -> DocumentMessage:
    return (
        M.document()
        .header(feature.text("发起", "标题"))
        .inline_section("切磋状态", M.status("待应战", tone="warning"), icon="combat")
        .section("邀约内容", icon="player")
        .field("邀约对象", M.text(target_name, tone="emphasis"))
        .row(
            ("我方修士", len(value.user_participants)),
            ("对方修士", len(value.target_participants)),
        )
        .field("有效时间", natural_deadline(value.expires_at))
        .small(feature.text("发起", "说明", {"目标": target_name}))
        .build()
    )


def report_id(value: DuelResult) -> str:
    """切磋战报的编号：战报页面按 `切磋:<发起者>:<编号>` 取画面。"""
    return f"切磋:{value.owner}:{value.challenge_id}"


def report_url(value: DuelResult) -> str:
    """战报地址：**只要编号**（`/battle/<切磋编号>`）。

    战报是非资产数据：按编号存在非资产库（`log_battle_reports`）里，与谁发起、存在谁名下
    都无关，所以地址里既不带中文、也不带冒号、更不带 owner——纯 ASCII 才不会被聊天客户端改坏。
    """
    return public_url("battle", value.challenge_id)


def result(
    feature: DuelFeature,
    value: DuelResult,
    challenger_name: str,
    target_name: str,
) -> DocumentMessage:
    winner = feature.winner_label(value.winner, challenger_name, target_name)
    return (
        M.document()
        .header(feature.text("结果", "标题"))
        .inline_section("切磋状态", M.status("已结束", tone="positive"), icon="combat")
        .section("战果", icon="status")
        .field("胜方", M.text(winner, tone="positive"))
        .row(
            (challenger_name, len(value.user_participants)),
            (target_name, len(value.target_participants)),
        )
        .row(("行动", value.actions), ("战斗事件", value.events))
        .field(
            feature.text("结果", "完整战报"),
            M.link("打开战报", report_url(value)),
        )
        .build()
    )


def rejected() -> DocumentMessage:
    return (
        M.document()
        .header("切磋邀约")
        .inline_section("邀约状态", M.status("已拒绝", tone="muted"), icon="status")
        .build()
    )


def error(feature: DuelFeature, message: str) -> DocumentMessage:
    return (
        M.document()
        .section(feature.text("错误", "标题"), icon="notice")
        .line(M.status("切磋失败", tone="danger"), " ", sentence(message))
        .build()
    )


__all__ = ["challenge", "error", "rejected", "report_id", "report_url", "result"]
