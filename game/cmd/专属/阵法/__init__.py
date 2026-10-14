"""地点专属阵法浏览与炼阵命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.lianzhen import FormationCraftFeatureError
from game.features.presentation import ItemRefError, parse_item_ref

from ...command import GameCommand
from . import reply
from launch.adapter import MessageContext
from typing import Any

def _grade_prefix(feature: Any, value: str) -> str:
    """按核心口径受理品级的三种写法，吐命令内部用的单字。

    三种写法（黄品／黄／01）的受理归阵法玩法；命令层只转交，不再自己去问资产核心。
    """

    return feature.grade_prefix(value)


def _request(
    message: str, usage: str
) -> tuple[str, str, dict[str, int] | None]:
    raw = str(message or "").strip()
    # 统一写法：整串就是一条指称，投入写在扩展位里
    # （例：圣品周天星斗大阵{兽宝=1944,灵矿=5832,灵植=3888}）——中文名与编号都受理。
    if "{" in raw and " " not in raw:
        try:
            ref = parse_item_ref(raw)
            materials = {
                name: int(value)
                for name, value in ref.extra
                if name in ("兽宝", "灵矿", "灵植")
            }
        except (ItemRefError, ValueError, KeyError, TypeError) as exc:
            # 扩展位写得不合规范（含模板占位符「数」这种）一律当用法错，回同一句提示，不炸。
            raise ValueError(usage) from exc
        if set(materials) != {"兽宝", "灵矿", "灵植"} or any(
            value < 1 for value in materials.values()
        ):
            raise ValueError(usage)
        return (
            ref.item,
            _grade_prefix(current_game_services().features.lianzhen, ref.grade),
            materials,
        )
    parts = raw.split()
    if len(parts) not in {2, 5}:
        raise ValueError(usage)
    try:
        grade = _grade_prefix(current_game_services().features.lianzhen, parts[1])
    except Exception as exc:  # noqa: BLE001 - 品级不认识时仍然给玩家同一句用法提示
        raise ValueError(usage) from exc
    investments = None
    if len(parts) == 5:
        values = tuple(int(value) for value in parts[2:])
        if any(value < 1 for value in values):
            raise ValueError("圣品三相投入必须是正整数")
        investments = dict(zip(("兽宝", "灵矿", "灵植"), values, strict=True))
    return parts[0], grade, investments


@GameCommand.command(
    cmd="阵法审查",
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "炼制",
            "summary": "查看此地阵师开放的阵法，或审看一座阵法的三相投入",
            "usage": (
                "阵法审查",
                "阵法审查 2",
                "阵法审查 周天星斗大阵 黄",
                "阵法审查 周天星斗大阵 圣 1944 5832 3888",
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
        identifier, grade, investments = _request(
        query, reply.text(feature.copy(), "错误", "阵法审查格式")
    )
        value = await feature.preview(user_id, identifier, grade, investments)
        await manager.send(
            reply.preview(feature.copy(), value, feature.preview_actions(value))
        )
    except (FormationCraftFeatureError, ValueError) as exc:
        await manager.send(reply.error(feature.copy(), str(exc), feature.format_actions(), command="阵法审查"))


@GameCommand.command(
    cmd="炼阵",
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "炼制",
            "summary": "请当地阵师把三相材料炼成一份一次性阵法",
            "usage": (
                "炼阵 圣品周天星斗大阵{兽宝=1944,灵矿=5832,灵植=3888}",
                "炼阵 <品级><阵法名>[{兽宝=数,灵矿=数,灵植=数}]",
                "炼阵 圣品周天星斗大阵 1944 5832 3888",  # 旧写法继续受理
            ),
            "side_effect": "消耗兽宝、灵矿和灵植，把阵法收入阵藏",
            "order": 66,
        },
    },
)
async def commit_formation(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.lianzhen
    try:
        identifier, grade, investments = _request(
        message, reply.text(feature.copy(), "错误", "炼阵格式")
    )
        value = await feature.form(
            user_id, message_context.request_id, identifier, grade, investments
        )
        await manager.send(
            reply.completed(feature.copy(), value, feature.completed_actions())
        )
    except (FormationCraftFeatureError, ValueError) as exc:
        await manager.send(reply.error(feature.copy(), str(exc), feature.format_actions(), command="炼阵"))


__all__ = []
