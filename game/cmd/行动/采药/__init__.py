"""采药：一个根命令 + 紧凑子命令。"""
from __future__ import annotations

import re
from typing import Any

from game.app import current_game_services
from game.features.caiyao import HerbGatheringFeatureError

from ...command import GameCommand
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from . import reply

_COMPACT = re.compile(r"^采药(?P<action>进度|结束|结果)(?:\s+(?P<args>.*))?$")


async def _enter(
    user_id: str, raw_message: str, message_context: MessageContext
) -> None:
    feature = current_game_services().features.caiyao
    try:
        entry = await feature.enter(
            user_id, message_context.request_id, raw_message
        )
    except HerbGatheringFeatureError as exc:
        await send_game_reply(
            reply.error(feature.copy(), str(exc), feature.format_actions())
        )
        return
    if entry.kind == "started" and entry.started is not None:
        await send_game_reply(
            reply.started(feature.copy(), entry.started, feature.started_actions())
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
            reply.settlement_page(
                feature.copy(),
                feature,
                entry.settlement,
                entry.page,
                feature.settlement_actions(entry.page, entry.total_pages),
            )
        )


@GameCommand.command(
    cmd="采药",
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "开始或查看一次采药；写子命令看进度、结束或翻结果",
            "usage": ("采药", "采药进度", "采药结束 [页码]", "采药结果 [页码]"),
            "side_effect": "裸命令空闲时开始采药；进行中显示进度；已结算后再次开始新采药",
            "order": 36,
        },
    },
)
async def herb_root(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    await _enter(user_id, message, message_context)


@GameCommand.regex(cmd=_COMPACT, metadata={"scope": "通用", "guard_rule": "已创建", "hidden": True})
async def herb_compact(user_id: str, raw_message: str, message_context: MessageContext, manager: Any, match: re.Match) -> None:
    await _enter(user_id, raw_message, message_context)


@GameCommand.command(
    cmd="药始",
    metadata={
        "hosting": {"activity": "采药", "phase": "start"},
        "scope": "通用",
        "guard_rule": "自主空闲且可行动",
        "hidden": True,
    },
)
async def herb_hosted_start(user_id: str, message_context: MessageContext, manager: Any) -> None:
    await _enter(user_id, "采药 开始", message_context)


@GameCommand.command(
    cmd="药终",
    metadata={
        "hosting": {"activity": "采药", "phase": "end"},
        "scope": "通用",
        "guard_rule": "已创建",
        "hidden": True,
    },
)
async def herb_hosted_end(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    await _enter(user_id, f"采药 结束 {message}".strip(), message_context)


__all__ = []
