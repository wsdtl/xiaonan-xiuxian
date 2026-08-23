"""玩家通用赠送命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.zengsong import GiftError, GiftSendCommand
from message import M

from ...command import GameCommand, HelpSpec


@GameCommand.command(scope="通用", cmd="赠送", guard_rule="自主空闲或休息", help=HelpSpec(category="资源", summary="向附近玩家赠送灵石或基础物资", usage=("赠送 玩家 灵石 数量", "赠送 玩家 物品编号 品级 数量"), side_effect="在同一事务中转移资产", order=83))
async def send(*, user_id: str, message: str, message_context, manager, **_) -> None:
    feature = current_game_services().features.zengsong
    try:
        parts = str(message or "").split()
        if len(parts) == 3 and parts[1] == "灵石":
            target = await feature.resolve_target(user_id, parts[0])
            value = await feature.send(GiftSendCommand(user_id, target, message_context.request_id, spirit_stones=int(parts[2])))
            await manager.send(M.document().header(feature.text("", "标题")).line(feature.text("", "灵石", 接收者=target, 数量=value.quantity)).build())
            return
        if len(parts) != 4:
            raise ValueError(feature.text("命令", "物品格式"))
        target = await feature.resolve_target(user_id, parts[0])
        item = current_game_services().core.item_catalog.inspect(parts[1])
        value = await feature.send(GiftSendCommand(user_id, target, message_context.request_id, item_id=item.item_id, grade_id=parts[2], quantity=int(parts[3])))
        await manager.send(M.document().header(feature.text("", "标题")).line(feature.text("", "物品", 接收者=target, 品级=value.grade_id, 名称=item.name, 数量=value.quantity)).build())
    except (GiftError, ValueError) as exc:
        await manager.send(M.document().section(feature.text("错误", "标题"), icon="notice").line(str(exc)).build())
