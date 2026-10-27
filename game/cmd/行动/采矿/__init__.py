"""采矿：一个根命令 + 紧凑子命令。"""
from __future__ import annotations

import re
from typing import Any

from game.app import current_game_services
from game.features.caikuang import OreGatheringFeatureError

from ...command import GameCommand
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from . import reply

_COMPACT = re.compile(r"^采矿(?P<action>进度|结束|结果)(?:\s+(?P<args>.*))?$")


def _split(message: str) -> tuple[str, str]:
    parts = str(message or "").strip().split(maxsplit=1)
    if not parts:
        return "", ""
    return parts[0], parts[1] if len(parts) > 1 else ""


async def _start(user_id: str, request_id: str) -> None:
    feature = current_game_services().features.caikuang
    try:
        result = await feature.start(user_id, request_id)
        await send_game_reply(reply.started(feature.copy(), result, feature.started_actions()))
    except OreGatheringFeatureError as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc), feature.format_actions()))


async def _progress(user_id: str) -> None:
    feature = current_game_services().features.caikuang
    try:
        result = await feature.progress(user_id)
        await send_game_reply(
            reply.progress(feature.copy(), feature, result, feature.progress_actions(result.can_end))
        )
    except OreGatheringFeatureError as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc), feature.format_actions()))


async def _settle(user_id: str, page_text: str, request_id: str) -> None:
    feature = current_game_services().features.caikuang
    try:
        page = 1 if not page_text else int(page_text)
    except ValueError:
        await send_game_reply(reply.error(feature.copy(), reply.text(feature.copy(), "错误", "写法"), feature.format_actions()))
        return
    try:
        result = await feature.settle(user_id, request_id)
        total_pages = 1 + len(result.users)
        if page < 1 or page > total_pages:
            raise OreGatheringFeatureError(f"页码必须在1至{total_pages}之间")
        await send_game_reply(
            reply.settlement_page(feature.copy(), feature, result, page, feature.settlement_actions(page, total_pages))
        )
    except OreGatheringFeatureError as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc), feature.format_actions()))


async def _dispatch(user_id: str, action: str, args: str, message_context: MessageContext) -> None:
    feature = current_game_services().features.caikuang
    if not action:
        try:
            result = await feature.progress(user_id)
            if result.settled and not result.can_end:
                await _start(user_id, message_context.request_id)
            else:
                await send_game_reply(
                    reply.progress(feature.copy(), feature, result, feature.progress_actions(result.can_end))
                )
        except OreGatheringFeatureError:
            await _start(user_id, message_context.request_id)
        return
    if action == "开始":
        await _start(user_id, message_context.request_id)
    elif action == "进度":
        await _progress(user_id)
    elif action in {"结束", "结果"}:
        await _settle(user_id, args, message_context.request_id)
    else:
        await send_game_reply(reply.error(feature.copy(), reply.text(feature.copy(), "错误", "写法"), feature.format_actions()))


@GameCommand.command(
    cmd="采矿",
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "开始或查看一次采矿；写子命令看进度、结束或翻结果",
            "usage": ("采矿", "采矿进度", "采矿结束 [页码]", "采矿结果 [页码]"),
            "side_effect": "裸命令空闲时开始采矿；进行中显示进度；已结算后再次开始新采矿",
            "order": 39,
        },
    },
)
async def ore_root(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    action, args = _split(message)
    await _dispatch(user_id, action, args, message_context)


@GameCommand.regex(cmd=_COMPACT, metadata={"scope": "通用", "guard_rule": "已创建", "hidden": True})
async def ore_compact(user_id: str, raw_message: str, message_context: MessageContext, manager: Any, match: re.Match) -> None:
    await _dispatch(user_id, match.group("action"), match.group("args") or "", message_context)


@GameCommand.command(
    cmd="矿始",
    metadata={
        "hosting": {"activity": "采矿", "phase": "start"},
        "scope": "通用",
        "guard_rule": "自主空闲且可行动",
        "hidden": True,
    },
)
async def ore_hosted_start(user_id: str, message_context: MessageContext, manager: Any) -> None:
    await _start(user_id, message_context.request_id)


@GameCommand.command(
    cmd="矿终",
    metadata={
        "hosting": {"activity": "采矿", "phase": "end"},
        "scope": "通用",
        "guard_rule": "已创建",
        "hidden": True,
    },
)
async def ore_hosted_end(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    await _settle(user_id, message, message_context.request_id)


__all__ = []
