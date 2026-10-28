"""宗门战：一个根命令 + 接受/拒绝/撤回。"""

from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.zongmen_zhan import SectWarError

from ...command import GameCommand
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from . import reply


def _feature():
    return current_game_services().features.zongmen_zhan


async def _view(user_id: str, message_context: MessageContext, raw: str) -> None:
    feature = _feature()
    try:
        if raw in {"接受", "拒绝", "撤回"}:
            method = {
                "接受": feature.accept,
                "拒绝": feature.reject,
                "撤回": feature.withdraw,
            }[raw]
            await send_game_reply(reply.view(feature, await method(user_id, message_context.request_id)))
            return
        parts = raw.split()
        if len(parts) == 2 and parts[1].isdecimal() and int(parts[1]) > 0:
            value = await feature.challenge(user_id, parts[0], int(parts[1]), message_context.request_id)
            await send_game_reply(reply.view(feature, value))
            return
        if not raw:
            try:
                value = await feature.current(user_id, message_context.request_id)
            except SectWarError:
                await send_game_reply(reply.intro(feature))
                return
            await send_game_reply(reply.view(feature, value))
            return
        await send_game_reply(
            reply.error(feature, feature.text("错误", "约战写法"), feature.format_actions("约战格式"))
        )
    except SectWarError as exc:
        await send_game_reply(reply.error(feature, feature.error(exc), feature.format_actions("约战格式")))


@GameCommand.command(
    cmd="宗门战",
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "宗门",
            "summary": "宗门战：无参数看介绍/当前，发宗门名与灵石约战，接受/拒绝/撤回",
            "usage": (
                "宗门战",
                "宗门战 对方宗门 灵石",
                "宗门战 接受",
                "宗门战 拒绝",
                "宗门战 撤回",
            ),
            "side_effect": "约战扣本宗押注；接受后立即开战；不改变战报入口",
            "order": 1,
        },
    },
)
async def sect_war_root(
    user_id: str, message: str, message_context: MessageContext, manager: Any
) -> None:
    await _view(user_id, message_context, str(message or "").strip())


__all__ = []
