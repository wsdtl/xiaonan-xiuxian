"""炼器：总览、只读目录与直接开炉。"""
from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.lianqi import ForgingFeatureError

from ...command import GameCommand
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from . import reply

def _error(feature: Any, message: str) -> object:
    return reply.error(feature.copy(), message, feature.format_actions(), command="炼器")


def _render(feature: Any, entry: Any) -> object:
    if entry.kind == "overview" and entry.overview is not None:
        return reply.overview(
            feature.copy(), entry.overview, feature.overview_actions()
        )
    if entry.kind == "preview" and entry.preview is not None:
        return reply.preview(
            feature.copy(), entry.preview, feature.preview_actions(entry.preview)
        )
    if entry.kind == "completed" and entry.result is not None:
        return reply.completed(
            feature.copy(), entry.result, feature.completed_actions()
        )
    if entry.kind == "law_list" and entry.laws is not None:
        return reply.law_list(feature.copy(), entry.laws)
    raise ValueError("炼器结果无效")


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
    try:
        entry = await feature.enter_direct(
            user_id, message_context.request_id, message
        )
        await send_game_reply(_render(feature, entry))
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
            "usage": ("炼器目录", "炼器目录 法器", "炼器目录 玄品无归劫锋"),
            "side_effect": "目录列表只读；单条详情才查这一条的材料，不直接消耗",
            "order": 62,
        },
    },
)
async def forging_catalog(user_id: str, message: str, manager: Any) -> None:
    feature = current_game_services().features.lianqi
    try:
        entry = await feature.enter_catalog(user_id, message)
        await send_game_reply(_render(feature, entry))
    except ValueError as exc:
        await send_game_reply(_error(feature, str(exc)))
    except ForgingFeatureError as exc:
        await send_game_reply(_error(feature, str(exc)))


__all__ = []
