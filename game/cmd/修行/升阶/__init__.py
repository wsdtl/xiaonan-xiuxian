"""通用升阶命令。"""

from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.shengjie import ShengjieError

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext


def _quantity(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise ShengjieError("数量必须是正整数") from exc
    if value < 1:
        raise ShengjieError("数量必须是正整数")
    return value


@GameCommand.command(
    cmd=("升阶", "提升品级"),
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "修行",
            "summary": "把一件基础材料升到更高品级",
            "usage": (
                "升阶 黄品岩露黄精 圣品",
                "升阶 黄品岩露黄精 天品 3",
            ),
            "side_effect": "消耗目标品级灵石，改变物品品级",
            "order": 70,
        },
    },
)
async def upgrade(
    user_id: str,
    message: str,
    message_context: MessageContext,
    manager: Any,
) -> None:
    feature = current_game_services().features.shengjie
    parts = str(message or "").split()
    if len(parts) not in (2, 3):
        await send_game_reply(
            reply.error(
                feature.copy(),
                "写法：升阶 <来源品级><物品> <目标品级> [数量]",
                "升阶 黄品岩露黄精 圣品",
            )
        )
        return
    try:
        quantity = _quantity(parts[2]) if len(parts) == 3 else 1
        value = await feature.upgrade_from_text(
            user_id,
            message_context.request_id,
            parts[0],
            parts[1],
            quantity,
        )
        await send_game_reply(reply.upgraded(feature.copy(), value))
    except ShengjieError as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc), "升阶 <来源品级><物品> <目标品级> [数量]"))


@GameCommand.command(
    cmd=("升阶方案",),
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "修行",
            "summary": "按当前库存列出缺失材料的升阶命令，只读",
            "usage": (
                "升阶方案 炼丹 一息续命丹 3",
                "升阶方案 炼器 无归劫锋",
                "升阶方案 炼阵 黄品叠翠盘根阵",
                "升阶方案 灵植 天品 2",
                "升阶方案 兽宝 澄波闻灵骨 天品 1",
            ),
            "side_effect": "只读，不消耗材料与灵石",
            "order": 71,
        },
    },
)
async def plan(
    user_id: str,
    message: str,
    message_context: MessageContext,
    manager: Any,
) -> None:
    feature = current_game_services().features.shengjie
    parts = str(message or "").split()
    if not parts:
        await send_game_reply(
            reply.error(
                feature.copy(),
                "写法：升阶方案 炼丹|炼器 <名称> [数量]，或 升阶方案 灵植|灵矿|兽宝 [编号] <目标品级> [数量]",
                "升阶方案 炼丹 一息续命丹 3",
            )
        )
        return
    try:
        kind = parts[0]
        if kind in ("炼丹", "炼器", "炼阵"):
            if len(parts) not in (2, 3):
                raise ShengjieError("写法：升阶方案 炼丹|炼器|炼阵 <名称> [数量]")
            quantity = _quantity(parts[2]) if len(parts) == 3 else 1
            value = await feature.plan_crafting(user_id, kind, parts[1], quantity)
        elif kind in ("灵植", "灵矿", "兽宝"):
            if len(parts) == 3:
                item_text, target_text, quantity_text = "", parts[1], parts[2]
            elif len(parts) == 4:
                item_text, target_text, quantity_text = parts[1], parts[2], parts[3]
            else:
                raise ShengjieError(
                    "写法：升阶方案 灵植|灵矿|兽宝 [编号] <目标品级> [数量]"
                )
            value = await feature.plan_material(
                user_id, kind, item_text, target_text, _quantity(quantity_text)
            )
        else:
            raise ShengjieError("升阶方案目前支持炼丹、炼器、炼阵、灵植、灵矿、兽宝")
        await send_game_reply(reply.plan(feature.copy(), value))
    except ShengjieError as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc), "升阶方案 <类别> ..."))


__all__ = []
