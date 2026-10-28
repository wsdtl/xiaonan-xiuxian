"""探险：玩家侧只保留「探险」与「结束探险 / 探险结束」。"""
from __future__ import annotations

from game.app import current_game_services
from game.features.tanxian import ExplorationFeatureError

from ...command import GameCommand
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from . import reply


async def _render(
    user_id: str, message_context: MessageContext, *, exiting: bool
) -> None:
    feature = current_game_services().features.tanxian
    try:
        entry = await (
            feature.exit(user_id, message_context.request_id)
            if exiting
            else feature.enter_bare(user_id, message_context.request_id)
        )
    except ExplorationFeatureError as exc:
        await send_game_reply(
            reply.error(feature.copy(), str(exc), feature.format_actions())
        )
        return
    if entry.kind == "started" and entry.started is not None:
        await send_game_reply(
            reply.started(feature.copy(), entry.started, feature.start_actions())
        )
    elif entry.kind == "progress" and entry.progress is not None:
        await send_game_reply(
            reply.progress(
                feature.copy(),
                entry.progress,
                feature.progress_actions(
                    entry.progress.ended, entry.progress.can_settle
                ),
            )
        )
    elif entry.kind == "settlement" and entry.settlement is not None:
        await send_game_reply(
            reply.settlement_summary(feature.copy(), feature, entry.settlement)
        )


@GameCommand.fullmatch(
    cmd="探险",
    metadata={
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "开始一次普通探险；进行中查看进度",
            "usage": ("探险",),
            "side_effect": "空闲时开始；进行中只查看进度；已结束后再发开新一轮",
            "order": 30,
        },
    },
)
async def exploration(user_id: str, message_context: MessageContext) -> None:
    await _render(user_id, message_context, exiting=False)


@GameCommand.fullmatch(
    cmd=("结束探险", "探险结束"),
    metadata={
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "结束当前探险并查看单屏总结",
            "usage": ("结束探险", "探险结束"),
            "side_effect": "立即结算当前探险；已结束时重看同一份总结",
            "order": 31,
        },
    },
)
async def end_exploration(
    user_id: str, message_context: MessageContext
) -> None:
    await _render(user_id, message_context, exiting=True)


__all__ = []
