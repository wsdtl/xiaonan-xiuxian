"""地点专属炼丹命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.liandan import AlchemyFeatureError

from ...command import GameCommand
from . import reply
from launch.adapter import MessageContext
from typing import Any

_CATEGORIES = frozenset({"恢复丹", "战丹", "突破丹", "特殊丹"})
_GRADES = ("黄品", "玄品", "地品", "天品", "圣品")


def _parse_recipe(query: str) -> tuple[str, str]:
    parts = query.split()
    grade = "黄品"
    if parts:
        token = parts[0]
        for name in _GRADES:
            short = name.removesuffix("品")
            for prefix in (name, short):
                if token.startswith(prefix):
                    grade = name
                    rest = token[len(prefix):]
                    parts = ([rest] if rest else []) + parts[1:]
                    break
            else:
                continue
            break
    return grade, " ".join(parts).strip()


@GameCommand.command(
    cmd="炼丹",
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "炼制",
            "summary": "查看当地丹师可炼丹药，或请丹师验看一颗丹药",
            "usage": ("炼丹", "炼丹 恢复丹", "炼丹 战丹 2", "炼丹 圣品聚气丹"),
            "side_effect": "只验药，不消耗材料",
            "order": 63,
        },
    },
)
async def inspect_alchemy(user_id: str, message: str, manager: Any) -> None:
    feature = current_game_services().features.liandan
    query = str(message or "").strip()
    try:
        if not query:
            value = await feature.overview(user_id)
            await manager.send(
                reply.overview(feature.copy(), value, feature.overview_actions())
            )
            return
        parts = query.split()
        if parts[0] in _CATEGORIES and len(parts) <= 2:
            page = 1 if len(parts) == 1 else int(parts[1])
            value = await feature.recipes(user_id, parts[0], page)
            await manager.send(
                reply.recipe_list(feature.copy(), value, feature.list_actions(value))
            )
            return
        grade, identifier = _parse_recipe(query)
        value = await feature.preview(user_id, identifier, grade)
        await manager.send(
            reply.preview(feature.copy(), value, feature.preview_actions(value))
        )
    except (AlchemyFeatureError, ValueError) as exc:
        await manager.send(reply.error(feature.copy(), str(exc), feature.format_actions(), command="炼丹"))


@GameCommand.command(
    cmd="开丹炉",
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "炼制",
            "summary": "请当地丹师按验药结果炼成一枚丹药",
            "usage": ("开丹炉 聚气丹", "开丹炉 圣品聚气丹",),
            "side_effect": "消耗一件兽宝和所需灵植，把丹药收入纳戒",
            "order": 64,
        },
    },
)
async def commit_alchemy(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.liandan
    query = str(message or "").strip()
    if not query:
        await manager.send(
            reply.error(
      feature.copy(), reply.text(feature.copy(), "错误", "写法"), feature.format_actions(), command="开丹炉"
  )
        )
        return
    try:
        grade, identifier = _parse_recipe(query)
        value = await feature.refine(user_id, message_context.request_id, identifier, grade)
        await manager.send(
            reply.completed(feature.copy(), value, feature.completed_actions())
        )
    except AlchemyFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc), feature.format_actions(), command="开丹炉"))


__all__ = []
