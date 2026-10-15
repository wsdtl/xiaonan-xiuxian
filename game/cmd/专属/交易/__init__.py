"""地点专属交易命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.jiaoyi import TradeFeatureError, TradePurchaseCommand

from game.features.presentation import ItemRefError, parse_item_and_grade

from ...command import GameCommand
from . import reply
from .site import router
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="交易",
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "资源",
            "summary": "查看当前位置固定出售的真意和气机",
            "usage": ("交易", "交易 真意", "交易 气机", "交易 真意 页码"),
            "side_effect": "只读查询，不消耗灵石",
            "order": 55,
        },
    },
)
async def inspect_trade(user_id: str, message: str, manager: Any) -> None:
    feature = current_game_services().features.jiaoyi
    parts = str(message or "").split()
    try:
        if not parts:
            value = await feature.overview(user_id)
            await manager.send(reply.overview(feature, value))
            return
        if len(parts) > 2 or parts[0] not in {"真意", "气机"}:
            raise TradeFeatureError(feature.copy("错误", "交易格式"))
        page_number = 1
        if len(parts) == 2:
            if not parts[1].isdecimal() or int(parts[1]) < 1:
                raise TradeFeatureError("交易页码必须是正整数")
            page_number = int(parts[1])
        value = await feature.page(user_id, parts[0], page_number)
        await manager.send(reply.page(feature, value))
    except TradeFeatureError as exc:
        await manager.send(reply.error(feature, str(exc), feature.format_actions(), command="交易"))


@GameCommand.command(
    cmd="购买",
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "资源",
            "summary": "从当前位置货架购买真意或气机",
            "usage": ("购买 01410049", "购买 01410049 3", "购买 <品级><物品> [数量]"),
            "side_effect": "扣除灵石，把对应数量收入修行资粮；单次最多买 50 个",
            "order": 56,
        },
    },
)
async def purchase_trade(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.jiaoyi
    try:
        # 统一语法：<品级><物品> [数量]；旧的「物品 品级」仍受理（见 game/cmd/item_ref.py）。
        item, grade, quantity = parse_item_and_grade(str(message or "").split())
    except ItemRefError:
        await manager.send(
            reply.error(
                feature,
                feature.copy("错误", "购买写法"),
                feature.format_actions(),
                command="购买",
            )
        )
        return
    try:
        value = await feature.purchase(
            TradePurchaseCommand(
                user_id,
                message_context.request_id,
                item,
                grade,
                quantity,
            )
        )
        await manager.send(reply.purchased(feature, value))
    except TradeFeatureError as exc:
        await manager.send(reply.error(feature, str(exc), feature.format_actions(), command="购买"))


__all__ = ["router"]
