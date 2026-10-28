"""闭关：玩家侧只保留「闭关」「出关」两条命令。"""
from __future__ import annotations

from game.app import current_game_services
from game.features.biguan import RetreatFeatureError

from ...command import GameCommand
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from . import reply


async def _render(
    user_id: str, message_context: MessageContext, *, exiting: bool
) -> None:
    feature = current_game_services().features.biguan
    try:
        entry = await (
            feature.exit(user_id, message_context.request_id)
            if exiting
            else feature.enter_bare(user_id, message_context.request_id)
        )
    except RetreatFeatureError as exc:
        await send_game_reply(
            reply.error(feature.copy(), str(exc), feature.format_actions())
        )
        return
    if entry.kind == "started" and entry.started is not None:
        await send_game_reply(
            reply.started(
                feature.copy(), entry.started, feature.started_actions()
            )
        )
    elif entry.kind == "progress" and entry.progress is not None:
        await send_game_reply(
            reply.progress(
                feature.copy(),
                feature,
                entry.progress,
                feature.progress_actions(entry.progress.can_end),
            )
        )
    elif entry.kind == "settlement" and entry.settlement is not None:
        await send_game_reply(
            reply.settlement_summary(feature.copy(), feature, entry.settlement)
        )


@GameCommand.fullmatch(
    cmd="闭关",
    metadata={
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "开始一次闭关；进行中查看进度",
            "usage": ("闭关",),
            "side_effect": "空闲时开始；进行中只查看进度；已出关后再发开新一轮",
            "order": 33,
        },
    },
)
async def retreat(user_id: str, message_context: MessageContext) -> None:
    await _render(user_id, message_context, exiting=False)


@GameCommand.fullmatch(
    cmd="出关",
    metadata={
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "结束当前闭关并查看出关总结",
            "usage": ("出关",),
            "side_effect": "立即结算当前闭关；已出关时重看同一份总结",
            "order": 34,
        },
    },
)
async def leave_retreat(user_id: str, message_context: MessageContext) -> None:
    await _render(user_id, message_context, exiting=True)


__all__ = []
