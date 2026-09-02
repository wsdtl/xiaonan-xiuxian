"""地点专属交易命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.jiaoyi import TradeFeatureError, TradePurchaseCommand

from ...command import GameCommand
from . import reply


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
async def inspect_trade(*, user_id: str, message: str, manager, **_) -> None:
    feature = current_game_services().features.jiaoyi
    parts = str(message or "").split()
    try:
        if not parts:
            value = await feature.overview(user_id)
            await manager.send(reply.overview(feature, value))
            return
        if len(parts) > 2 or parts[0] not in {"真意", "气机"}:
            raise TradeFeatureError("格式：交易 真意 [页码] / 交易 气机 [页码]")
        page_number = 1
        if len(parts) == 2:
            if not parts[1].isdecimal() or int(parts[1]) < 1:
                raise TradeFeatureError("交易页码必须是正整数")
            page_number = int(parts[1])
        value = await feature.page(user_id, parts[0], page_number)
        await manager.send(reply.page(feature, value))
    except TradeFeatureError as exc:
        await manager.send(reply.error(feature, str(exc)))


@GameCommand.command(
    cmd="购买",
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "资源",
            "summary": "从当前位置货架购买真意或气机",
            "usage": ("购买 编号或名称 品级", "购买 编号或名称 品级 数量"),
            "side_effect": "原子扣除灵石，并把对应数量收入修行资粮",
            "order": 56,
        },
    },
)
async def purchase_trade(
    *, user_id: str, message: str, message_context, manager, **_
) -> None:
    feature = current_game_services().features.jiaoyi
    parts = str(message or "").split()
    if len(parts) not in {2, 3} or (len(parts) == 3 and not parts[2].isdecimal()):
        await manager.send(reply.error(feature, "格式：购买 编号或名称 品级 [数量]"))
        return
    quantity = int(parts[2]) if len(parts) == 3 else 1
    try:
        value = await feature.purchase(
            TradePurchaseCommand(
                user_id,
                message_context.request_id,
                parts[0],
                parts[1],
                quantity,
            )
        )
        await manager.send(reply.purchased(feature, value))
    except TradeFeatureError as exc:
        await manager.send(reply.error(feature, str(exc)))


__all__ = []
