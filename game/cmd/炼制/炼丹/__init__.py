"""炼丹：总览、只读目录与直接炼制。"""
from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.liandan import AlchemyFeatureError
from game.features.presentation import ItemRefError, parse_item_ref

from ...command import GameCommand
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from . import reply


def _direct(message: str) -> tuple[object, int]:
    parts = str(message or "").strip().split()
    quantity = 1
    if len(parts) > 1 and parts[-1].isdecimal():
        quantity = int(parts[-1])
        parts = parts[:-1]
    if not parts:
        raise ValueError("缺少丹药名")
    ref = parse_item_ref(" ".join(parts))
    if not ref.grade:
        raise ValueError("请写品级，例：炼丹 黄品聚气丹")
    return ref, quantity


def _error(feature: Any, message: str) -> object:
    return reply.error(feature.copy(), message, feature.format_actions(), command="炼丹")


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
    query = str(message or "").strip()
    try:
        if not query:
            value = await feature.overview(user_id)
            await send_game_reply(
                reply.overview(feature.copy(), value, feature.overview_actions())
            )
            return
        ref, quantity = _direct(query)
        value = await feature.preview(user_id, ref.item, ref.grade, quantity)
        if value.can_refine:
            result = await feature.refine(
                user_id, message_context.request_id, ref.item, ref.grade, quantity
            )
            await send_game_reply(
                reply.completed(feature.copy(), result, feature.completed_actions())
            )
        else:
            await send_game_reply(
                reply.preview(feature.copy(), value, feature.preview_actions(value))
            )
    except ValueError as exc:
        await send_game_reply(_error(feature, str(exc)))
    except ItemRefError as exc:
        await send_game_reply(_error(feature, str(exc)))
    except AlchemyFeatureError as exc:
        await send_game_reply(_error(feature, str(exc)))


@GameCommand.command(
    cmd="炼丹目录",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "炼制",
            "summary": "只读查看丹方目录；不查库存、不炼药、不消耗",
            "usage": ("炼丹目录", "炼丹目录 恢复丹", "炼丹目录 恢复丹 2"),
            "side_effect": "只读；目录计数是丹方数量，不表示当前材料是否齐备",
            "order": 64,
        },
    },
)
async def alchemy_catalog(user_id: str, message: str, manager: Any) -> None:
    feature = current_game_services().features.liandan
    query = str(message or "").strip()
    try:
        if not query:
            value = await feature.overview(user_id)
            await send_game_reply(
                reply.overview(feature.copy(), value, feature.overview_actions())
            )
            return
        parts = query.split()
        category = parts[0]
        page = int(parts[1]) if len(parts) == 2 and parts[1].isdecimal() else 1
        if len(parts) > 2 or (len(parts) == 2 and not parts[1].isdecimal()):
            raise ValueError("写法：炼丹目录 [类别] [页码]")
        value = await feature.recipes(user_id, category, page)
        await send_game_reply(
            reply.recipe_list(feature.copy(), value, feature.list_actions(value))
        )
    except ValueError as exc:
        await send_game_reply(_error(feature, str(exc)))
    except AlchemyFeatureError as exc:
        await send_game_reply(_error(feature, str(exc)))


__all__ = []
