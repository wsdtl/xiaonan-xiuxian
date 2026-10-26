"""先天灵宝查看与执掌命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.xiantian_lingbao import (
    InnateTreasureEquipRequest,
    InnateTreasureFeatureConflictError,
    InnateTreasureFeatureError,
)

from ...command import GameCommand
from . import reply
from .site import router
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="先天灵宝",
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "修行",
            "summary": "查看灵宝谱和当前执掌的先天灵宝",
            "usage": ("先天灵宝", "先天灵宝 页码"),
            "side_effect": "只读查询，不改变灵宝槽",
            "order": 50,
        },
    },
)
async def show_innate_treasures(user_id: str, message: str, manager: Any) -> None:
    feature = current_game_services().features.xiantian_lingbao
    raw = message.strip()
    if raw and not raw.isdecimal():
        await send_game_reply(reply.error(feature, feature.copy("错误格式"), feature.format_actions()))
        return
    try:
        await send_game_reply(
            reply.view(feature, await feature.inspect(user_id, int(raw or 1)))
        )
    except InnateTreasureFeatureError as exc:
        await send_game_reply(reply.error(feature, str(exc), feature.format_actions()))


@GameCommand.command(
    cmd="灵宝谱",
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "修行",
            "summary": "查看这个世界一共存在哪些先天灵宝（全谱，与你自己有没有无关）",
            "usage": ("灵宝谱", "灵宝谱 页码"),
            "side_effect": "只读查询，不改变灵宝槽",
            "order": 55,
        },
    },
)
async def show_innate_treasure_catalog(user_id: str, message: str, manager: Any) -> None:
    feature = current_game_services().features.xiantian_lingbao
    raw = message.strip()
    if raw and not raw.isdecimal():
        await send_game_reply(reply.error(feature, feature.copy("错误格式"), feature.format_actions()))
        return
    try:
        await send_game_reply(
            reply.catalog(feature, await feature.catalog(int(raw or 1)))
        )
    except InnateTreasureFeatureError as exc:
        await send_game_reply(reply.error(feature, str(exc), feature.format_actions()))


@GameCommand.command(
    cmd="执掌灵宝",
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "修行",
            "summary": "从个人灵宝谱中选择一件先天灵宝执掌",
            "usage": ("执掌灵宝 斩仙飞刀", "执掌灵宝 编号或名称",),
            "side_effect": "替换唯一先天灵宝槽，不消耗灵宝",
            "order": 60,
        },
    },
)
async def equip_innate_treasure(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.xiantian_lingbao
    try:
        result = await feature.equip(
            InnateTreasureEquipRequest(
                user_id, message_context.request_id, message.strip()
            )
        )
        await send_game_reply(reply.equipped(feature, result))
    except (InnateTreasureFeatureError, InnateTreasureFeatureConflictError) as exc:
        await send_game_reply(reply.error(feature, str(exc), feature.format_actions()))


__all__ = ["router"]
