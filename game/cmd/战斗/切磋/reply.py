"""切磋命令回复构造。"""

from __future__ import annotations

from ...actions import CommandAction
from ...presentation import error_document

from typing import Sequence

from game.features.qiecuo import DuelChallenge, DuelFeature, DuelResult
from message import Action, DocumentMessage, M

from ...presentation import natural_deadline, sentence


def challenge(feature: DuelFeature, value: DuelChallenge, target_name: str) -> DocumentMessage:
    return (
        M.document()

        .inline_section("状态", M.status("待应战", tone="warning"), icon="game.swords")
        .section("邀约内容", icon="game.role")
        .field(
            "邀约对象",
            M.command(target_name, f"查看 {target_name}"),
        )
        .row(
            ("我方修士", len(value.user_participants)),
            ("对方修士", len(value.target_participants)),
        )
        .field("有效时间", natural_deadline(value.expires_at))
        .small(feature.text("发起", "说明", {"目标": target_name}))
        .actions(
            (
                Action("duel.accept", "接受切磋", "接受切磋"),
                Action(
                    "duel.reject",
                    "拒绝切磋",
                    "拒绝切磋",
                    style="secondary",
                ),
            )
        )
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

        .inline_section("状态", M.status("已结束", tone="positive"), icon="game.swords")
        .section("战果", icon="game.seed")
        .field("胜方", M.text(winner, tone="positive"))
        .row(
            (challenger_name, len(value.user_participants)),
            (target_name, len(value.target_participants)),
        )
        .row(("行动", value.actions), ("战斗事件", value.events))
        .build()
    )


def rejected() -> DocumentMessage:
    return (
        M.document()

        .inline_section("邀约", M.status("已拒绝", tone="muted"), icon="game.seed")
        .build()
    )


def error(
    feature: DuelFeature, message: str, actions: Sequence[CommandAction] = ()
) -> DocumentMessage:
    # 形状统一走 error_document（game/cmd/presentation.py），行为与原来一致。
    return error_document(        feature.text("错误", "标题"), "game.pin_doc", "切磋失败", sentence(message), tone="danger",
        actions=actions,
    )


__all__ = ["challenge", "error", "rejected", "result"]
