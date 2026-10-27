"""宗门战：一个状态根 + 紧凑子命令。"""
from __future__ import annotations

import re
from collections.abc import Awaitable
from typing import Any

from game.app import current_game_services
from game.features.zongmen_zhan import SectWarError, SectWarFeature, SectWarView

from ...command import GameCommand
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from . import reply


def _feature() -> SectWarFeature:
    return current_game_services().features.zongmen_zhan


async def _run(operation: Awaitable[SectWarView]) -> None:
    try:
        await send_game_reply(reply.view(_feature(), await operation))
    except SectWarError as exc:
        await send_game_reply(
            reply.error(_feature(), _feature().error(exc), _feature().format_actions("约战格式"))
        )


async def _challenge(user_id: str, args: str, request_id: str) -> None:
    parts = str(args or "").split()
    try:
        if len(parts) != 2 or not parts[1].isdecimal() or int(parts[1]) < 1:
            raise ValueError
        value = await _feature().challenge(user_id, parts[0], int(parts[1]), request_id)
        await send_game_reply(reply.view(_feature(), value))
    except ValueError:
        await send_game_reply(
            reply.error(_feature(), _feature().text("错误", "约战写法"), _feature().format_actions("约战格式"))
        )
    except SectWarError as exc:
        await send_game_reply(
            reply.error(_feature(), _feature().error(exc), _feature().format_actions("约战格式"))
        )


async def _current(user_id: str, war_id: str, request_id: str) -> None:
    try:
        value = (
            await _feature().view(user_id, war_id)
            if war_id
            else await _feature().current(user_id, request_id)
        )
        await send_game_reply(reply.view(_feature(), value))
    except SectWarError as exc:
        await send_game_reply(
            reply.error(_feature(), _feature().error(exc), _feature().format_actions("约战格式"))
        )


async def _history(user_id: str, raw: str) -> None:
    text = str(raw or "").strip()
    try:
        if text and (not text.isdecimal() or int(text) < 1):
            raise ValueError
        await send_game_reply(
            reply.history(_feature(), await _feature().history(user_id, int(text or 1)))
        )
    except ValueError:
        await send_game_reply(
            reply.error(_feature(), _feature().text("错误", "战况写法"), _feature().format_actions("战录格式"))
        )
    except SectWarError as exc:
        await send_game_reply(
            reply.error(_feature(), _feature().error(exc), _feature().format_actions("约战格式"))
        )


async def _reports(user_id: str, raw: str) -> None:
    text = str(raw or "").strip()
    try:
        if text and (not text.isdecimal() or int(text) < 1):
            raise ValueError
        await send_game_reply(
            reply.recent_reports(
                _feature(),
                await current_game_services().features.zhanbao.my_reports(
                    user_id, kind="宗门战", page=int(text or 1)
                ),
            )
        )
    except ValueError:
        await send_game_reply(
            reply.error(_feature(), _feature().text("错误", "战况写法"), _feature().format_actions("战录格式"))
        )


@GameCommand.command(
    cmd="宗门战",
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "宗门",
            "summary": "查看当前宗门战；用紧凑子命令约战、接战、锁阵、开战、看战况与战录",
            "usage": (
                "宗门战",
                "宗门战约战 宗门名 灵石数量",
                "宗门战接战",
                "宗门战锁阵",
                "宗门战开战",
                "宗门战况 [战书编号]",
                "宗门战录 [页码]",
                "宗门战报 [页码]",
            ),
            "side_effect": "约战扣本宗押注；开战消耗阵法、战丹与恢复丹；查看与战录只读",
            "order": 1,
        },
    },
)
async def sect_war_root(
    user_id: str, message: str, message_context: MessageContext, manager: Any
) -> None:
    # 根命令只做状态；动作走紧凑隐藏路由，保证各动作仍使用自己的守卫。
    if str(message or "").strip():
        await send_game_reply(
            reply.error(_feature(), _feature().text("错误", "约战写法"), _feature().format_actions("约战格式"))
        )
        return
    await _current(user_id, "", message_context.request_id)


@GameCommand.regex(
    cmd=re.compile(r"^宗门战约战(?:\s+(?P<args>.*))?$"),
    metadata={"scope": "通用", "guard_rule": "宗门战发起", "hidden": True},
)
async def sect_war_challenge(user_id: str, raw_message: str, message_context: MessageContext, manager: Any, match: re.Match) -> None:
    await _challenge(user_id, match.group("args") or "", message_context.request_id)


@GameCommand.regex(
    cmd=re.compile(r"^宗门战(?P<action>接战|拒战|撤战|锁阵)$"),
    metadata={"scope": "通用", "guard_rule": "宗门战待命", "hidden": True},
)
async def sect_war_ready(user_id: str, raw_message: str, message_context: MessageContext, manager: Any, match: re.Match) -> None:
    action = match.group("action")
    feature = _feature()
    if action == "接战":
        await _run(feature.accept(user_id, message_context.request_id))
    elif action == "拒战":
        await _run(feature.reject(user_id, message_context.request_id))
    elif action == "撤战":
        await _run(feature.withdraw(user_id, message_context.request_id))
    elif action == "锁阵":
        await _run(feature.lock(user_id, message_context.request_id))


@GameCommand.regex(
    cmd=re.compile(r"^宗门战(?P<action>解阵|开战|停战)$"),
    metadata={"scope": "通用", "guard_rule": "宗门战操作", "hidden": True},
)
async def sect_war_operate(user_id: str, raw_message: str, message_context: MessageContext, manager: Any, match: re.Match) -> None:
    action = match.group("action")
    feature = _feature()
    if action == "解阵":
        await _run(feature.unlock(user_id, message_context.request_id))
    elif action == "开战":
        await _run(feature.start(user_id, message_context.request_id))
    elif action == "停战":
        await _run(feature.cancel(user_id, message_context.request_id))


@GameCommand.regex(
    cmd=re.compile(r"^宗门战况(?:\s+(?P<war_id>.*))?$"),
    metadata={"scope": "通用", "guard_rule": "已创建", "hidden": True},
)
async def sect_war_current(user_id: str, raw_message: str, message_context: MessageContext, manager: Any, match: re.Match) -> None:
    await _current(user_id, match.group("war_id") or "", message_context.request_id)


@GameCommand.regex(
    cmd=re.compile(r"^宗门战录(?:\s+(?P<page>.*))?$"),
    metadata={"scope": "通用", "guard_rule": "已创建", "hidden": True},
)
async def sect_war_history(user_id: str, raw_message: str, message_context: MessageContext, manager: Any, match: re.Match) -> None:
    await _history(user_id, match.group("page") or "")


@GameCommand.regex(
    cmd=re.compile(r"^宗门战报(?:\s+(?P<page>.*))?$"),
    metadata={"scope": "通用", "guard_rule": "已创建", "hidden": True},
)
async def sect_war_reports(user_id: str, raw_message: str, message_context: MessageContext, manager: Any, match: re.Match) -> None:
    await _reports(user_id, match.group("page") or "")


__all__ = []
