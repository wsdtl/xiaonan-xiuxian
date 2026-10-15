"""人物培养通用命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.presentation import ItemRefError, parse_item_ref
from game.features.renwu_peiyang import (
    CharacterBreakthroughRequest,
    CharacterCultivationConflictError,
    CharacterCultivationFeatureError,
    CharacterEquipRequest,
    CharacterLawRequest,
)

from ...command import GameCommand
from . import reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.fullmatch(
    cmd="人物培养",
    metadata={
        "scope": "通用",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "修行",
            "summary": "查看人物修为、修行槽与本命武器培养状态",
            "usage": ("人物培养",),
            "side_effect": "只查看，不会改变人物状态",
            "order": 10,
        },
    },
)
async def show_character_cultivation(user_id: str, manager: Any) -> None:
    feature = current_game_services().features.renwu_peiyang
    try:
        result = await feature.inspect(user_id)
        await manager.send(reply.view(feature, result))
    except CharacterCultivationFeatureError as exc:
        await manager.send(reply.error(feature, str(exc), feature.format_actions()))


@GameCommand.command(
    cmd="人物装配",
    metadata={
        "scope": "通用",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "修行",
            "summary": "把功法或一份真意、气机装入人物槽位",
            "usage": ("人物装配 功法 黄品五岳镇界镇岳诀 1", "人物装配 类别 <品级><物品> 孔位",),
            "side_effect": "功法保留所有权；真意和气机消耗一份。有「保留被替换资粮」的先天灵宝时，被替换的那份回修行资粮；否则原槽内容消失",
            "order": 20,
        },
    },
)
async def equip_character(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.renwu_peiyang
    parts = message.split()
    # 新写法：<类别> <品级><物品> <孔位>（3 段）；旧写法：<类别> <物品> <品级> <孔位>（4 段）仍受理。
    if len(parts) not in {3, 4} or not parts[-1].isdecimal():
        # 参数不对时直接把这条子命令的格式印出来，别只让人去翻帮助。
        await manager.send(
            reply.error(feature, feature.copy("错误", "装配写法"), feature.format_actions())
        )
        return
    category, slot = parts[0], int(parts[-1])
    if len(parts) == 4:
        content, grade = parts[1], parts[2]
    else:
        try:
            ref = parse_item_ref(parts[1])
        except ItemRefError:
            await manager.send(
                reply.error(feature, feature.copy("错误", "装配写法"), feature.format_actions())
            )
            return
        content, grade = ref.item, ref.grade
    try:
        result = await feature.equip(
            CharacterEquipRequest(
                user_id,
                message_context.request_id,
                category,
                content,
                grade,
                slot,
            )
        )
        await manager.send(reply.equipped(feature, result))
    except (CharacterCultivationFeatureError, CharacterCultivationConflictError) as exc:
        await manager.send(reply.error(feature, str(exc), feature.format_actions()))


@GameCommand.command(
    cmd="人物突破",
    metadata={
        "scope": "通用",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "修行",
            "summary": "消耗对应突破丹为人物突破境界",
            "usage": ("人物突破 小还丹", "人物突破 丹药编号或名称",),
            "side_effect": "消耗纳戒中最低品级的一枚对应突破丹；须当前境界已满级且该境界还没突破过，突破抬高意境阶上限时会顺带发道行",
            "order": 30,
        },
    },
)
async def breakthrough_character(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.renwu_peiyang
    try:
        result = await feature.breakthrough(
            CharacterBreakthroughRequest(
                user_id, message_context.request_id, message.strip()
            )
        )
        await manager.send(reply.breakthrough(feature, result))
    except (CharacterCultivationFeatureError, CharacterCultivationConflictError) as exc:
        # 名字写错时别让人猜：把本境界的候选丹一并端出来（算不出来就照旧只报错）。
        try:
            offer = await feature.breakthrough_offer(user_id)
        except (CharacterCultivationFeatureError, CharacterCultivationConflictError):
            offer = None
        await manager.send(
            reply.error(feature, str(exc), feature.format_actions(), offer)
        )


@GameCommand.command(
    cmd="人物覆炼",
    metadata={
        "scope": "通用",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "修行",
            "summary": "把器藏中的器律覆入人物本命武器",
            "usage": ("人物覆炼 太白惊鸿 1", "人物覆炼 器律编号或名称 孔位",),
            "side_effect": "消耗器藏中的一份器律并覆盖指定孔位",
            "order": 40,
        },
    },
)
async def forge_character_law(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.renwu_peiyang
    parts = message.rsplit(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdecimal():
        await manager.send(
            reply.error(feature, feature.copy("错误", "覆炼写法"), feature.format_actions())
        )
        return
    try:
        result = await feature.forge_law(
            CharacterLawRequest(
                user_id,
                message_context.request_id,
                parts[0],
                int(parts[1]),
            )
        )
        await manager.send(reply.forged(feature, result))
    except (CharacterCultivationFeatureError, CharacterCultivationConflictError) as exc:
        await manager.send(reply.error(feature, str(exc), feature.format_actions()))


__all__ = []
