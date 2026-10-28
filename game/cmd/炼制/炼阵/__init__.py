"""炼阵：总览、只读目录与直接炼阵。"""
from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.lianzhen import FormationChoiceError, FormationCraftFeatureError
from ...command import GameCommand
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from . import reply


def _error(feature: Any, message: str, command: str) -> object:
    return reply.error(feature.copy(), message, feature.format_actions(), command=command)


def _render(feature: Any, entry: Any) -> object:
    if entry.kind == "overview" and entry.overview is not None:
        return reply.overview(
            feature.copy(), entry.overview, feature.overview_actions(entry.overview)
        )
    if entry.kind == "choose_grade":
        return reply.choose_grade(feature.copy(), entry.identifier)
    if entry.kind == "preview" and entry.preview is not None:
        return reply.preview(
            feature.copy(), entry.preview, feature.preview_actions(entry.preview)
        )
    if entry.kind == "completed" and entry.result is not None:
        return reply.completed(
            feature.copy(), entry.result, feature.completed_actions()
        )
    raise ValueError("炼阵结果无效")


@GameCommand.command(
    cmd="炼阵",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "炼制",
            "summary": "查看炼阵总览，或直接炼一座阵法",
            "usage": ("炼阵", "炼阵 黄品叠翠盘根阵", "炼阵 圣品叠翠盘根阵 100 200 300"),
            "side_effect": "写完整阵法且三相材料足时消耗材料并收入阵藏；缺材料只回预览",
            "order": 65,
        },
    },
)
async def formation_root(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.lianzhen
    try:
        entry = await feature.enter(
            user_id, message_context.request_id, message
        )
        result = getattr(entry, "result", None)
        preview = result.preview if result is not None else getattr(entry, "preview", None)
        title = f"炼阵 {preview.formation.name}" if preview is not None else "炼阵"
        await send_game_reply(_render(feature, entry), title=title)
    except FormationChoiceError as exc:
        await send_game_reply(
            reply.choose(feature.copy(), exc, command="炼阵"), title="炼阵"
        )
    except (FormationCraftFeatureError, ValueError) as exc:
        await send_game_reply(_error(feature, str(exc), "炼阵"), title="炼阵")


@GameCommand.command(
    cmd="炼阵目录",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "炼制",
            "summary": "只读查看可炼阵法目录；不查库存、不炼阵、不消耗",
            "usage": ("炼阵目录", "炼阵目录 2", "炼阵目录 黄品叠翠盘根阵"),
            "side_effect": "目录列表只读；单条详情才查这一条的三相材料，不直接消耗",
            "order": 66,
        },
    },
)
async def formation_catalog(user_id: str, message: str, manager: Any) -> None:
    feature = current_game_services().features.lianzhen
    try:
        entry = await feature.enter_catalog(user_id, message)
        await send_game_reply(_render(feature, entry), title="炼阵目录")
    except FormationChoiceError as exc:
        await send_game_reply(
            reply.choose(feature.copy(), exc, command="炼阵目录"),
            title="炼阵目录",
        )
    except (FormationCraftFeatureError, ValueError) as exc:
        await send_game_reply(_error(feature, str(exc), "炼阵目录"), title="炼阵目录")


__all__ = []
