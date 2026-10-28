"""普通探险：一个根命令 + 紧凑子命令。"""
from __future__ import annotations

import re
from typing import Any

from game.app import current_game_services
from game.features.tanxian import ExplorationFeatureError

from ...command import GameCommand
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from . import reply

_COMPACT = re.compile(r"^探险(?P<action>进度|结束|结果)(?:\s+(?P<args>.*))?$")


async def _enter(
    user_id: str, raw_message: str, message_context: MessageContext
) -> None:
    feature = current_game_services().features.tanxian
    try:
        entry = await feature.enter(
            user_id, message_context.request_id, raw_message
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
            reply.settlement_page(
                feature.copy(),
                feature,
                entry.settlement,
                entry.page,
                feature.settlement_actions(entry.page, entry.total_pages),
            )
        )


@GameCommand.command(
    cmd="探险",
    metadata={
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "开始或查看一次普通探险；写子命令看进度、结算或翻结果",
            "usage": ("探险", "探险进度", "探险结束 [页码]", "探险结果 [页码]"),
            "side_effect": "裸命令空闲时开始探险；进行中显示进度；已结算后再次开始新探险",
            "order": 30,
        },
    },
)
async def exploration_root(
    user_id: str, message: str, message_context: MessageContext, manager: Any
) -> None:
    await _enter(user_id, message, message_context)


@GameCommand.regex(
    cmd=_COMPACT,
    metadata={"scope": "专属", "guard_rule": "已创建", "hidden": True},
)
async def exploration_compact(
    user_id: str,
    raw_message: str,
    message_context: MessageContext,
    manager: Any,
    match: re.Match,
) -> None:
    await _enter(user_id, raw_message, message_context)


@GameCommand.command(
    cmd="探始",
    metadata={
        "hosting": {"activity": "探险", "phase": "start"},
        "scope": "专属",
        "guard_rule": "自主空闲且可行动",
        "hidden": True,
    },
)
async def exploration_hosted_start(
    user_id: str, message_context: MessageContext, manager: Any
) -> None:
    await _enter(user_id, "探险 开始", message_context)


@GameCommand.command(
    cmd="探终",
    metadata={
        "hosting": {"activity": "探险", "phase": "end"},
        "scope": "专属",
        "guard_rule": "已创建",
        "hidden": True,
    },
)
async def exploration_hosted_end(
    user_id: str, message: str, message_context: MessageContext, manager: Any
) -> None:
    await _enter(user_id, f"探险 结束 {message}".strip(), message_context)


__all__ = []
