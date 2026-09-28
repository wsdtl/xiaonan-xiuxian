"""切磋命令回复构造。"""

from __future__ import annotations

from game.features.qiecuo import DuelChallenge, DuelFeature, DuelResult
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
            M.text(f"切磋:{value.owner}:{value.challenge_id}", tone="muted"),
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


__all__ = ["challenge", "error", "rejected", "result"]
