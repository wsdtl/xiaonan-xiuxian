"""物品统一使用入口：只查使用档案，按端口转发。"""
from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.presentation import ItemRefError, parse_item_ref
from game.features.shiyong import UseError, UseRedirect, UseRequest

from ...branching import BranchParseError, branch_menu_for
from ...command import GameCommand
from ...reply_composer import send_game_reply
from . import reply
from launch.adapter import MessageContext


def _split(message: str) -> tuple[str, str | None]:
    parts = str(message or "").split()
    if not parts:
        raise ValueError("缺少物品")
    if len(parts) == 1:
        return parts[0], None
    if len(parts) != 2:
        raise ValueError("写法")
    return parts[0], parts[1]


@GameCommand.command(
    cmd="使用",
    metadata={
        "scope": "通用",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "查看与工具",
            "summary": "使用一件物品：构筑入槽、灵宝执掌、阵法入槽、丹药服用或按提示转到专属入口",
            "usage": (
                "使用 黄品五岳镇界镇岳诀 1",
                "使用 玄品太白惊鸿 2",
                "使用 斩仙飞刀",
                "使用 小还丹 道侣",
                "使用 黄品叠翠盘根阵",
            ),
            "side_effect": "按使用档案执行；阵法入槽可替换旧阵，正式战一次性消耗，切磋不消耗",
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
    feature = current_game_services().features.shiyong
    try:
        ref_text, candidate = _split(message)
        ref = parse_item_ref(ref_text)
        plan = await feature.plan(
            UseRequest(
                user_id,
                message_context.request_id,
                ref.item,
                grade=ref.grade,
                treasure=ref.treasure,
            )
        )
        if isinstance(plan, UseRedirect):
            await send_game_reply(reply.redirect(plan))
            return
        selected = candidate
        if selected is None:
            selected = plan.description.default
        if not selected:
            candidates = plan.description.candidates
            if len(candidates) == 1:
                selected = candidates[0].value
            elif not candidates:
                selected = ""
            else:
                branch = (
                    f">使用 {plan.description.display} "
                    + "|".join(item.value for item in candidates)
                )
                await send_game_reply(branch_menu_for(branch))
                return
        outcome = await feature.execute(plan, selected)
        copy_feature = getattr(current_game_services().features, plan.profile.port)
        await send_game_reply(reply.render(outcome, copy_feature))
    except BranchParseError:
        await send_game_reply(reply.error(feature, feature.copy("写法")))
    except UseError as exc:
        await send_game_reply(reply.error(feature, str(exc)))
    except (ValueError, ItemRefError):
        await send_game_reply(reply.error(feature, feature.copy("写法")))


__all__ = []
