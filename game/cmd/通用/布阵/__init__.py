"""通用布阵命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.buzhen import FormationArmFeatureError

from ...command import GameCommand
from . import reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="布阵",
    metadata={
        "scope": "通用",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "战斗",
            "summary": "从阵藏取出一座阵法，备入下一场正式战斗",
            "usage": ("布阵 阵藏条目编号", "布阵 周天星斗大阵 黄"),
            "side_effect": "阵法离开阵藏并进入待战状态，一次只能准备一座",
            "order": 67,
        },
    },
)
async def arm_formation(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.buzhen
    query = str(message or "").strip()
    if not query:
        await manager.send(
            reply.error(feature.copy(), "格式：布阵 阵法名 [品级]")
        )
        return
    try:
        value = await feature.arm(user_id, message_context.request_id, query)
        await manager.send(
            reply.completed(feature.copy(), value, _treasure_text(value))
        )
    except FormationArmFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


def _treasure_text(value: object) -> str:
    """待战阵法带先天灵宝时给一句人话：名字 · 加成方向（数值来自灵宝实体，不自己编）。

    没有灵宝就返回空串——卡片那边整段不显示，也不写「无灵宝」三个字。
    """
    prepared = getattr(value, 'prepared', None)
    treasure_id = str(getattr(prepared, 'treasure_id', '') or '')
    if not treasure_id:
        return ""
    services = current_game_services()
    try:
        raw = dict(services.core.data.entity('先天灵宝', treasure_id))
    except Exception:
        return treasure_id
    name = str(raw.get('名称') or treasure_id)
    effect = raw.get('规则介入') or {}
    if not hasattr(effect, 'get'):
        return name
    ability = str(effect.get('能力') or '')
    scale = ""
    for field, suffix in (('比例', '%'), ('数量', ''), ('次数', ''), ('进度', '')):
        if effect.get(field) is not None:
            value_text = effect[field]
            scale = (
                str(int(round(float(value_text) * 100))) + suffix if suffix else str(value_text)
            )
            break
    tail = (ability + ' ' + scale).strip()
    return (name + ' · ' + tail) if tail else name

__all__ = []
