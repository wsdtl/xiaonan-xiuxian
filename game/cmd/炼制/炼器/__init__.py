"""炼器：总览、只读目录与直接开炉。"""
from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.lianqi import ForgingFeatureError

from ...command import GameCommand
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from . import reply

_STAGES = frozenset({"灵器", "法器", "法宝", "后天灵宝"})


def _direct(message: str) -> tuple[str, int]:
    parts = str(message or "").strip().split()
    quantity = 1
    if len(parts) > 1 and parts[-1].isdecimal():
        quantity = int(parts[-1])
        parts = parts[:-1]
    if not parts:
        raise ValueError("缺少器律名")
    return " ".join(parts), quantity


def _error(feature: Any, message: str) -> object:
    return reply.error(feature.copy(), message, feature.format_actions(), command="炼器")


@GameCommand.command(
    cmd="炼器",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "炼制",
            "summary": "查看炼器总览，或直接炼一份器律",
            "usage": ("炼器", "炼器 玄品无归劫锋", "炼器 玄品无归劫锋 2"),
            "side_effect": "写完整器律且唯一、材料足时消耗材料并开炉；缺材料或多解只回预览",
            "order": 61,
        },
    },
)
async def forging_root(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.lianqi
    query = str(message or "").strip()
    try:
        if not query:
            value = await feature.overview(user_id)
            await send_game_reply(reply.overview(feature.copy(), value, feature.overview_actions()))
            return
        identifier, quantity = _direct(query)
        value = await feature.preview(user_id, identifier, quantity)
        if value.can_forge:
            result = await feature.forge(user_id, message_context.request_id, identifier, quantity)
            await send_game_reply(reply.completed(feature.copy(), result, feature.completed_actions()))
        else:
            await send_game_reply(reply.preview(feature.copy(), value, feature.preview_actions(value)))
    except ValueError as exc:
        await send_game_reply(_error(feature, str(exc)))
    except ForgingFeatureError as exc:
        await send_game_reply(_error(feature, str(exc)))


@GameCommand.command(
    cmd="炼器目录",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "炼制",
            "summary": "只读查看器律目录；不查库存、不开炉、不消耗",
            "usage": ("炼器目录", "炼器目录 法器"),
            "side_effect": "只读；目录计数是器律数量，不表示当前材料是否齐备",
            "order": 62,
        },
    },
)
async def forging_catalog(user_id: str, message: str, manager: Any) -> None:
    feature = current_game_services().features.lianqi
    query = str(message or "").strip()
    try:
        if not query:
            value = await feature.overview(user_id)
            await send_game_reply(reply.overview(feature.copy(), value, feature.overview_actions()))
            return
        if query not in _STAGES:
            raise ValueError("写法：炼器目录 [器阶]")
        value = await feature.laws(user_id, query)
        await send_game_reply(reply.law_list(feature.copy(), value))
    except ValueError as exc:
        await send_game_reply(_error(feature, str(exc)))
    except ForgingFeatureError as exc:
        await send_game_reply(_error(feature, str(exc)))


__all__ = []
