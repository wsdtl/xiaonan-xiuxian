"""通用升阶命令。"""

from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.shengjie import ShengjieError

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext


@GameCommand.command(
    cmd="升阶",
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
    try:
        value = await feature.enter_upgrade(
            user_id, message_context.request_id, message
        )
        await send_game_reply(
            reply.upgraded(feature.copy(), value),
            title=(
                f"升阶 {value.source_grade_name}{value.item_name}"
                f" → {value.target_grade_name}"
            ),
        )
    except ShengjieError as exc:
        await send_game_reply(
            reply.error(
                feature.copy(),
                str(exc),
                "升阶 <来源品级><物品> <目标品级> [数量]",
            ),
            title="升阶",
        )


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
    try:
        value = await feature.enter_plan(user_id, message)
        await send_game_reply(
            reply.plan(feature.copy(), value),
            title="升阶方案",
        )
    except ShengjieError as exc:
        await send_game_reply(
            reply.error(feature.copy(), str(exc), "升阶方案 <类别> ..."),
            title="升阶方案",
        )


__all__ = []
