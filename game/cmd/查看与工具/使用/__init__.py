"""物品统一使用入口：只查使用档案，按端口转发。"""
from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.presentation import ItemRefError
from game.features.shiyong import UseError

from ...branching import BranchParseError, branch_menu
from ...command import GameCommand
from ...reply_composer import send_game_reply
from . import reply
from launch.adapter import MessageContext


def _copy_feature(plan: Any, target: str) -> Any:
    key = plan.profile.port
    if key == "law":
        key = "daolv_peiyang" if target == "道侣" else "renwu_peiyang"
    return getattr(current_game_services().features, key)


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
                "使用 太白惊鸿 道侣 2",
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
        entry = await feature.enter(
            user_id, message_context.request_id, message
        )
        name = (
            entry.plan.request.name
            if entry.plan is not None and entry.plan.request.name
            else ""
        )
        if entry.kind == "redirect" and entry.redirect is not None:
            await send_game_reply(
                reply.redirect(entry.redirect),
                title=f"使用 {name or entry.redirect.title}",
            )
        elif entry.kind == "branch":
            await send_game_reply(branch_menu(entry.commands), title="使用")
        elif (
            entry.kind == "outcome"
            and entry.outcome is not None
            and entry.plan is not None
        ):
            await send_game_reply(
                reply.render(
                    entry.outcome,
                    _copy_feature(entry.plan, entry.target),
                ),
                title=f"使用 {name}" if name else "使用",
            )
    except BranchParseError:
        await send_game_reply(reply.error(feature, feature.copy("写法")), title="使用")
    except UseError as exc:
        await send_game_reply(reply.error(feature, str(exc)), title="使用")
    except (ValueError, ItemRefError):
        await send_game_reply(reply.error(feature, feature.copy("写法")), title="使用")


__all__ = []
