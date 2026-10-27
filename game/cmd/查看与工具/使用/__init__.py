"""物品统一使用入口：只接第一类（功法/真意/气机/器律）的构筑使用。"""
from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.presentation import ItemRefError, parse_item_ref
from game.features.renwu_peiyang import (
    CharacterCultivationConflictError,
    CharacterCultivationFeatureError,
)

from ...branching import BranchParseError, branch_menu_for
from ...command import GameCommand
from ...reply_composer import send_game_reply
from . import reply
from launch.adapter import MessageContext


def _split(message: str) -> tuple[str, int | None]:
    parts = str(message or "").split()
    if not parts:
        raise ValueError("缺少物品")
    if len(parts) == 1:
        return parts[0], None
    if len(parts) != 2 or not parts[1].isdecimal():
        raise ValueError("写法")
    position = int(parts[1])
    if position < 1:
        raise ValueError("位置必须是正整数")
    return parts[0], position


@GameCommand.command(
    cmd="使用",
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "查看与工具",
            "summary": "使用一件物品：功法/真意/气机入槽，器律入本命武器孔",
            "usage": (
                "使用 黄品五岳镇界镇岳诀 1",
                "使用 玄品太白惊鸿 2",
            ),
            "side_effect": "按物品类别装配或覆炼；功法保留所有权，真意/气机消耗一份",
            "order": 15,
        },
    },
)
async def use_item(
    user_id: str,
    message: str,
    message_context: MessageContext,
    manager: Any,
) -> None:
    feature = current_game_services().features.renwu_peiyang
    try:
        ref_text, position = _split(message)
        ref = parse_item_ref(ref_text)
        target = await feature.resolve_use_target(user_id, ref.item)
        if target.category != "器律" and not ref.grade:
            raise CharacterCultivationFeatureError(feature.copy("使用", "缺品级"))
        if position is None:
            if len(target.slots) == 1:
                position = target.slots[0]
            else:
                branch = (
                    f">使用 {ref.grade}{target.name} "
                    + "|".join(str(slot) for slot in target.slots)
                )
                await send_game_reply(branch_menu_for(branch))
                return
        result = await feature.use(
            user_id, message_context.request_id, target, ref.grade, position
        )
        if target.category == "器律":
            await send_game_reply(reply.forged(feature, result))
        else:
            await send_game_reply(reply.equipped(feature, result))
    except BranchParseError:
        await send_game_reply(reply.error(feature, feature.copy("使用", "写法")))
    except (CharacterCultivationFeatureError, CharacterCultivationConflictError) as exc:
        await send_game_reply(reply.error(feature, str(exc)))
    except (ValueError, ItemRefError) as exc:
        await send_game_reply(
            reply.error(feature, feature.copy("使用", "写法"))
            if str(exc) in {"缺少物品", "写法", "位置必须是正整数"}
            else reply.error(feature, str(exc))
        )


__all__ = []
