"""玩家通用赠送命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.zengsong import GiftError, GiftSendCommand

from ...command import GameCommand
from . import reply


@GameCommand.command(
    cmd="赠送",
    metadata={
        "scope": "通用",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "资源",
            "summary": "向指定玩家赠送灵石或基础物资（可按用户编号跨地点名送达）",
            "usage": ("赠送 玩家 灵石 数量", "赠送 玩家 物品编号 品级 数量"),
            "side_effect": "在同一事务中转移资产",
            "order": 83,
        },
    },
)
async def send(*, user_id: str, message: str, message_context, manager, **_) -> None:
    feature = current_game_services().features.zengsong
    try:
        parts = str(message or "").split()
        if len(parts) == 3 and parts[1] == "灵石":
            target = await feature.resolve_target(user_id, parts[0])
            target_name = await feature.target_name(target)
            value = await feature.send(
                GiftSendCommand(
                    user_id,
                    target,
                    message_context.request_id,
                    spirit_stones=int(parts[2]),
                )
            )
            await manager.send(reply.stones(feature, target_name, value))
            return
        if len(parts) != 4:
            raise ValueError(feature.text("命令", "物品格式"))
        target = await feature.resolve_target(user_id, parts[0])
        target_name = await feature.target_name(target)
        item = current_game_services().core.item_catalog.inspect(parts[1])
        value = await feature.send(
            GiftSendCommand(
                user_id,
                target,
                message_context.request_id,
                item_id=item.item_id,
                grade_id=parts[2],
                quantity=int(parts[3]),
            )
        )
        grade = current_game_services().core.asset.grade(value.grade_id).name
        await manager.send(
            reply.item(
                feature,
                target_name,
                value,
                grade_name=grade,
                item_name=item.name,
            )
        )
    except (GiftError, ValueError) as exc:
        await manager.send(reply.error(feature, str(exc)))
