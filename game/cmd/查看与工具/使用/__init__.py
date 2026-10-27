"""物品统一使用入口：只查使用档案，按端口转发。"""
from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.presentation import ItemRefError, parse_item_ref
from game.features.shiyong import UseError, UseOption, UseRedirect, UseRequest

from ...branching import BranchParseError, branch_menu
from ...command import GameCommand
from ...reply_composer import send_game_reply
from . import reply
from launch.adapter import MessageContext


def _split(message: str) -> tuple[str, tuple[str, ...]]:
    parts = str(message or "").split()
    if not parts:
        raise ValueError("缺少物品")
    if len(parts) > 3:
        raise ValueError("写法")
    return parts[0], tuple(parts[1:])


def _copy_feature(plan: Any, target: str) -> Any:
    key = plan.profile.port
    if key == "law":
        key = "daolv_peiyang" if target == "道侣" else "renwu_peiyang"
    return getattr(current_game_services().features, key)


def _commands(display: str, options: tuple[UseOption, ...]) -> tuple[str, ...]:
    result = []
    for option in options:
        parts = [f"使用 {display}"]
        if option.target:
            parts.append(option.target)
        if option.position:
            parts.append(str(option.position))
        result.append(" ".join(parts))
    return tuple(result)


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
        ref_text, args = _split(message)
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
        options = plan.description.options
        target = ""
        position = 0
        if plan.profile.target != "无":
            first = args[0] if args else ""
            if first and any(option.target == first for option in options):
                target = first
                args = args[1:]
            elif first and not first.isdecimal():
                raise UseError(f"目标不可用：{first}")
            elif args or plan.profile.position == "无":
                target = plan.description.target_default
        if args:
            if plan.profile.position == "无":
                raise UseError("这件物品不需要位置")
            if len(args) != 1 or not args[0].isdecimal():
                raise UseError(f"位置不可用：{args[0]}")
            position = int(args[0])
        if not options:
            outcome = await feature.execute(plan, target, position)
            await send_game_reply(reply.render(outcome, _copy_feature(plan, target)))
            return
        if plan.profile.target != "无" and plan.profile.position != "无":
            if not target:
                filtered = options
            else:
                filtered = tuple(option for option in options if option.target == target)
            if not position:
                if len(filtered) == 1:
                    target = filtered[0].target
                    position = filtered[0].position
                else:
                    await send_game_reply(branch_menu(_commands(plan.description.display, filtered)))
                    return
        elif plan.profile.position != "无":
            if not position:
                if len(options) == 1:
                    position = options[0].position
                else:
                    await send_game_reply(branch_menu(_commands(plan.description.display, options)))
                    return
        elif plan.profile.target != "无":
            if not target:
                if len(options) == 1:
                    target = options[0].target
                else:
                    await send_game_reply(branch_menu(_commands(plan.description.display, options)))
                    return
        outcome = await feature.execute(plan, target, position)
        await send_game_reply(reply.render(outcome, _copy_feature(plan, target)))
    except BranchParseError:
        await send_game_reply(reply.error(feature, feature.copy("写法")))
    except UseError as exc:
        await send_game_reply(reply.error(feature, str(exc)))
    except (ValueError, ItemRefError):
        await send_game_reply(reply.error(feature, feature.copy("写法")))


__all__ = []
