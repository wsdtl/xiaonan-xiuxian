"""先天灵宝查看与执掌命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.xiantian_lingbao import InnateTreasureFeatureError

from ...command import GameCommand
from . import reply
from .site import router
from ...reply_composer import send_game_reply


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
async def show_innate_treasures(user_id: str, message: str) -> None:
    feature = current_game_services().features.xiantian_lingbao
    try:
        await send_game_reply(
            reply.view(feature, await feature.inspect_from_text(user_id, message)),
            title="先天灵宝",
        )
    except InnateTreasureFeatureError as exc:
        await send_game_reply(
            reply.error(feature, str(exc), feature.format_actions()),
            title="先天灵宝",
        )


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
async def show_innate_treasure_catalog(message: str) -> None:
    feature = current_game_services().features.xiantian_lingbao
    try:
        await send_game_reply(
            reply.catalog(feature, await feature.catalog_from_text(message)),
            title="灵宝谱",
        )
    except InnateTreasureFeatureError as exc:
        await send_game_reply(
            reply.error(feature, str(exc), feature.format_actions()),
            title="灵宝谱",
        )


__all__ = ["router"]
