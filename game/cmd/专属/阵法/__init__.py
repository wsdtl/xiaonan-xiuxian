"""地点专属阵法浏览与炼阵命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.lianzhen import FormationCraftFeatureError

from ...command import GameCommand
from . import reply
from launch.adapter import MessageContext
from typing import Any

_GRADES = frozenset({"黄", "玄", "地", "天", "圣"})


def _request(message: str) -> tuple[str, str, dict[str, int] | None]:
    parts = str(message or "").strip().split()
    if len(parts) not in {2, 5} or parts[1] not in _GRADES:
        raise ValueError("格式：阵法/炼阵 阵法编号或名称 品级 [兽宝数 灵矿数 灵植数]")
    investments = None
    if len(parts) == 5:
        values = tuple(int(value) for value in parts[2:])
        if any(value < 1 for value in values):
            raise ValueError("圣品三相投入必须是正整数")
        investments = dict(zip(("兽宝", "灵矿", "灵植"), values, strict=True))
    return parts[0], parts[1], investments


@GameCommand.command(
    cmd="阵法",
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "炼制",
            "summary": "查看此地阵师开放的阵法，或审看一座阵法的三相投入",
            "usage": (
                "阵法",
                "阵法 2",
                "阵法 周天星斗大阵 黄",
                "阵法 周天星斗大阵 圣 1944 5832 3888",
            ),
            "side_effect": "只审材，不消耗材料",
            "order": 65,
        },
    },
)
async def inspect_formation(user_id: str, message: str, manager: Any) -> None:
    feature = current_game_services().features.lianzhen
    query = str(message or "").strip()
    try:
        if not query or query.isdecimal():
            page = int(query) if query else 1
            value = await feature.overview(user_id, page)
            await manager.send(
                reply.overview(feature.copy(), value, feature.overview_actions(value))
            )
            return
        identifier, grade, investments = _request(query)
        value = await feature.preview(user_id, identifier, grade, investments)
        await manager.send(
            reply.preview(feature.copy(), value, feature.preview_actions(value))
        )
    except (FormationCraftFeatureError, ValueError) as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


@GameCommand.command(
    cmd="炼阵",
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "炼制",
            "summary": "请当地阵师把三相材料炼成一份一次性阵法",
            "usage": ("炼阵 阵法编号或名称 品级 [圣品兽宝数 灵矿数 灵植数]",),
            "side_effect": "原子消耗兽宝、灵矿和灵植，并把阵法收入阵藏",
            "order": 66,
        },
    },
)
async def commit_formation(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.lianzhen
    try:
        identifier, grade, investments = _request(message)
        value = await feature.form(
            user_id, message_context.request_id, identifier, grade, investments
        )
        await manager.send(
            reply.completed(feature.copy(), value, feature.completed_actions())
        )
    except (FormationCraftFeatureError, ValueError) as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


__all__ = []
