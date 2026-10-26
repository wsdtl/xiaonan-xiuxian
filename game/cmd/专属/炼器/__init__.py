"""地点专属炼器命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.lianqi import ForgingFeatureError

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any

_STAGES = frozenset({"灵器", "法器", "法宝", "后天灵宝"})


def _parse_forge(query: str) -> tuple[str, int]:
    parts = query.split()
    quantity = 1
    if len(parts) > 1 and parts[-1].isdigit():
        quantity = int(parts[-1])
        parts = parts[:-1]
    return " ".join(parts).strip(), quantity


@GameCommand.command(
    cmd="炼器",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "炼制",
            "summary": "查看可炼器律，或请当地工匠审看一条器律的材料",
            "usage": ("炼器", "炼器 灵器", "炼器 太白惊鸿"),
            "side_effect": "只审材，不消耗材料",
            "order": 61,
        },
    },
)
async def inspect_forging(user_id: str, message: str, manager: Any) -> None:
    feature = current_game_services().features.lianqi
    query = str(message or "").strip()
    try:
        if not query:
            value = await feature.overview(user_id)
            await send_game_reply(
                reply.overview(feature.copy(), value, feature.overview_actions())
            )
        elif query in _STAGES:
            value = await feature.laws(user_id, query)
            await send_game_reply(reply.law_list(feature.copy(), value))
        else:
            value = await feature.preview(user_id, query)
            await send_game_reply(
                reply.preview(feature.copy(), value, feature.preview_actions(value))
            )
    except ForgingFeatureError as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc), feature.format_actions(), command="炼器"))


@GameCommand.command(
    cmd="开炉",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "炼制",
            "summary": "请当地工匠按审材结果炼成一份器律",
            "usage": ("开炉 太白惊鸿", "开炉 器律编号或名称",),
            "side_effect": "消耗兽宝和灵矿，把一份器律收入器藏",
            "order": 62,
        },
    },
)
async def commit_forging(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.lianqi
    query = str(message or "").strip()
    if not query:
        await send_game_reply(
            reply.error(
      feature.copy(), reply.text(feature.copy(), "错误", "写法"), feature.format_actions(), command="开炉"
  )
        )
        return
    try:
        identifier, quantity = _parse_forge(query)
        value = await feature.forge(
            user_id, message_context.request_id, identifier, quantity
        )
        await send_game_reply(
            reply.completed(feature.copy(), value, feature.completed_actions())
        )
    except ForgingFeatureError as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc), feature.format_actions(), command="开炉"))


__all__ = []
