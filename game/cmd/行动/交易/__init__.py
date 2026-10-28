"""地点专属交易命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.jiaoyi import TradeFeatureError, TradePurchaseCommand

from game.features.presentation import ItemRefError, parse_item_and_grade

from ...command import GameCommand
from . import reply
from .site import router
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="交易",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "行动",
            "summary": "查看当前位置货架",
            "usage": ("交易", "交易 类别", "交易 类别 页码"),
            "side_effect": "只读查询，不消耗灵石",
            "order": 55,
        },
    },
)
async def inspect_trade(user_id: str, message: str, manager: Any) -> None:
    feature = current_game_services().features.jiaoyi
    try:
        entry = await feature.enter_query(user_id, message)
    except TradeFeatureError as exc:
        await send_game_reply(
            reply.error(
                feature,
                str(exc),
                feature.format_actions(),
                command="交易",
            ),
            title="交易",
        )
        return
    if entry.kind == "overview" and entry.overview is not None:
        await send_game_reply(reply.overview(feature, entry.overview), title="交易")
    elif entry.kind == "page" and entry.page is not None:
        await send_game_reply(reply.page(feature, entry.page), title="交易")


@GameCommand.command(
    cmd="购买",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "行动",
            "summary": "从当前位置货架购买商品",
            "usage": ("购买 黄品抢刻", "购买 黄品抢刻 3", "购买 <品级><物品> [数量]"),
            "side_effect": "扣除灵石，把商品存入对应资产；单次最多买 50 个",
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
        await send_game_reply(
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
        await send_game_reply(
            reply.purchased(feature, value),
            title=f"购买 {value.product.grade_name}{value.product.name}",
        )
    except TradeFeatureError as exc:
        await send_game_reply(
            reply.error(feature, str(exc), feature.format_actions(), command="购买"),
            title="购买",
        )


__all__ = ["router"]
