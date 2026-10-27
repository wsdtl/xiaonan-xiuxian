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


def _split(message: str) -> tuple[str, str]:
    parts = str(message or "").strip().split(maxsplit=1)
    if not parts:
        return "", ""
    return parts[0], parts[1] if len(parts) > 1 else ""


async def _start(user_id: str, request_id: str) -> None:
    feature = current_game_services().features.tanxian
    try:
        result = await feature.start(user_id, request_id)
        await send_game_reply(
            reply.started(feature.copy(), result, feature.start_actions())
        )
    except ExplorationFeatureError as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc), feature.format_actions()))


async def _progress(user_id: str) -> None:
    feature = current_game_services().features.tanxian
    try:
        result = await feature.progress(user_id)
        await send_game_reply(
            reply.progress(
                feature.copy(),
                result,
                feature.progress_actions(result.ended, result.can_settle),
            )
        )
    except ExplorationFeatureError as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc), feature.format_actions()))


async def _settle(user_id: str, page_text: str, request_id: str) -> None:
    feature = current_game_services().features.tanxian
    try:
        page = 1 if not page_text else int(page_text)
    except ValueError:
        await send_game_reply(
            reply.error(feature.copy(), reply.text(feature.copy(), "错误", "写法"), feature.format_actions())
        )
        return
    try:
        result = await feature.settle(user_id, request_id)
        total_pages = 1 + len(result.users)
        if page < 1 or page > total_pages:
            raise ExplorationFeatureError(f"页码必须在1至{total_pages}之间")
        await send_game_reply(
            reply.settlement_page(
                feature.copy(),
                feature,
                result,
                page,
                feature.settlement_actions(page, total_pages),
            )
        )
    except ExplorationFeatureError as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc), feature.format_actions()))


async def _dispatch(
    user_id: str,
    action: str,
    args: str,
    message_context: MessageContext,
) -> None:
    feature = current_game_services().features.tanxian
    if not action:
        try:
            result = await feature.progress(user_id)
            if result.ended and not result.can_settle:
                await _start(user_id, message_context.request_id)
            else:
                await send_game_reply(
                    reply.progress(
                        feature.copy(),
                        result,
                        feature.progress_actions(result.ended, result.can_settle),
                    )
                )
        except ExplorationFeatureError:
            await _start(user_id, message_context.request_id)
        return
    if action == "开始":
        await _start(user_id, message_context.request_id)
    elif action == "进度":
        await _progress(user_id)
    elif action in {"结束", "结果"}:
        await _settle(user_id, args, message_context.request_id)
    else:
        await send_game_reply(
            reply.error(feature.copy(), reply.text(feature.copy(), "错误", "写法"), feature.format_actions())
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
    action, args = _split(message)
    await _dispatch(user_id, action, args, message_context)


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
    await _dispatch(
        user_id, match.group("action"), match.group("args") or "", message_context
    )


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
    await _start(user_id, message_context.request_id)


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
    await _settle(user_id, message, message_context.request_id)


__all__ = []
