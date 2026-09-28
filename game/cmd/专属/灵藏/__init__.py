"""宗门洞天专属灵藏命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.zongmen_lingcang import LingcangFeatureError

from ...command import GameCommand
from . import reply
from launch.adapter import MessageContext
from typing import Any

_CATEGORIES = frozenset({"灵植", "灵矿", "兽宝"})


@GameCommand.command(
    cmd="灵藏",
    metadata={
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "在本宗洞天分类查看宗门基础资源",
            "usage": ("灵藏", "灵藏 灵植", "灵藏 灵矿 2"),
            "side_effect": "只读查询；灵藏只捐入不取用，成品由万珍殿发放",
            "order": 80,
        },
    },
)
async def show_lingcang(user_id: str, message: str, manager: Any) -> None:
    feature = current_game_services().features.zongmen_lingcang
    parts = str(message or "").split()
    try:
        if len(parts) > 2:
            raise LingcangFeatureError("格式：灵藏 [灵植/灵矿/兽宝] [页码]")
        category = parts[0] if parts else "全部"
        page_number = _positive(parts[1], "灵藏页码") if len(parts) == 2 else 1
        value = await feature.page(user_id, category, page_number)
        await manager.send(
            reply.page(feature.copy(), value, feature.page_actions(value))
        )
    except LingcangFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


@GameCommand.command(
    cmd=("捐藏", "捐入灵藏"),
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "行动",
            "summary": "向本宗灵藏捐献基础材料或灵石",
            "usage": (
                "捐入灵藏 灵石 数量",
                "捐入灵藏 灵植/灵矿/兽宝 编号或名称 品级 数量",
            ),
            "side_effect": "原子扣除个人资源并计入宗门灵藏；灵藏只捐入不取用，成品由万珍殿发放",
            "order": 81,
        },
    },
)
async def donate_lingcang(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.zongmen_lingcang
    parts = str(message or "").split()
    try:
        if len(parts) == 2 and parts[0] == "灵石":
            quantity = _positive(parts[1], "灵石数量")
            result = await feature.donate_stones(
                user_id, message_context.request_id, quantity
            )
            await manager.send(reply.donated_stones(feature.copy(), quantity, result))
            return
        if len(parts) != 4 or parts[0] not in _CATEGORIES:
            raise LingcangFeatureError(
                "格式：捐入灵藏 灵石 数量，或捐入灵藏 类别 编号或名称 品级 数量"
            )
        result = await feature.donate_material(
            user_id,
            message_context.request_id,
            parts[0],
            parts[1],
            parts[2],
            _positive(parts[3], "捐献数量"),
        )
        await manager.send(reply.donated_material(feature.copy(), result))
    except LingcangFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


def _positive(value: str, label: str) -> int:
    if not value.isdecimal() or int(value) < 1:
        raise LingcangFeatureError(f"{label}必须是正整数")
    return int(value)


__all__ = []
