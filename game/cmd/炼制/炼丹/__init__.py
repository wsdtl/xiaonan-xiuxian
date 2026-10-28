"""炼丹：总览、只读目录与直接炼制。"""
from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.liandan import AlchemyFeatureError
from game.features.presentation import ItemRefError

from ...command import GameCommand
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from . import reply

def _error(feature: Any, message: str) -> object:
    return reply.error(feature.copy(), message, feature.format_actions(), command="炼丹")


def _render(feature: Any, entry: Any) -> object:
    if entry.kind == "overview" and entry.overview is not None:
        return reply.overview(
            feature.copy(), entry.overview, feature.overview_actions()
        )
    if entry.kind == "choose_grade":
        return reply.choose_grade(feature.copy(), entry.item)
    if entry.kind == "preview" and entry.preview is not None:
        return reply.preview(
            feature.copy(), entry.preview, feature.preview_actions(entry.preview)
        )
    if entry.kind == "completed" and entry.result is not None:
        return reply.completed(
            feature.copy(), entry.result, feature.completed_actions()
        )
    if entry.kind == "recipes" and entry.recipes is not None:
        return reply.recipe_list(
            feature.copy(), entry.recipes, feature.list_actions(entry.recipes)
        )
    raise ValueError("炼丹结果无效")


@GameCommand.command(
    cmd="炼丹",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "炼制",
            "summary": "查看丹方总览，或直接炼一枚丹药",
            "usage": ("炼丹", "炼丹 黄品聚气丹", "炼丹 黄品聚气丹 3"),
            "side_effect": "写成品级和丹名且唯一、材料足时消耗材料并成丹；缺材料或多解只回预览",
            "order": 63,
        },
    },
)
async def alchemy_root(
    user_id: str, message: str, message_context: MessageContext, manager: Any
) -> None:
    feature = current_game_services().features.liandan
    try:
        entry = await feature.enter_direct(
            user_id, message_context.request_id, message
        )
        result = getattr(entry, "result", None)
        preview = result.preview if result is not None else getattr(entry, "preview", None)
        title = (
            f"炼丹 {preview.medicine_grade_name}{preview.recipe.medicine_name}"
            if preview is not None
            else "炼丹"
        )
        await send_game_reply(_render(feature, entry), title=title)
    except ValueError as exc:
        await send_game_reply(_error(feature, str(exc)), title="炼丹")
    except ItemRefError as exc:
        await send_game_reply(_error(feature, str(exc)), title="炼丹")
    except AlchemyFeatureError as exc:
        await send_game_reply(_error(feature, str(exc)), title="炼丹")


@GameCommand.command(
    cmd="炼丹目录",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "炼制",
            "summary": "只读查看丹方目录；不查库存、不炼药、不消耗",
            "usage": ("炼丹目录", "炼丹目录 恢复丹", "炼丹目录 恢复丹 2", "炼丹目录 黄品聚气丹"),
            "side_effect": "目录列表只读；单条详情才查这一条的材料，不直接消耗",
            "order": 64,
        },
    },
)
async def alchemy_catalog(user_id: str, message: str, manager: Any) -> None:
    feature = current_game_services().features.liandan
    try:
        entry = await feature.enter_catalog(user_id, message)
        await send_game_reply(_render(feature, entry), title="炼丹目录")
    except ItemRefError as exc:
        await send_game_reply(_error(feature, str(exc)), title="炼丹目录")
    except ValueError as exc:
        await send_game_reply(_error(feature, str(exc)), title="炼丹目录")
    except AlchemyFeatureError as exc:
        await send_game_reply(_error(feature, str(exc)), title="炼丹目录")


__all__ = []
