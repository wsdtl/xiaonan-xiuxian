"""宗门洞天专属藏经阁命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.zongmen_cangjing import CangjingFeatureError

from ...command import GameCommand
from . import reply


@GameCommand.command(
    cmd="藏经阁",
    metadata={
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "查看本宗成员共享的最高品级功法",
            "usage": ("藏经阁", "藏经阁 2"),
            "side_effect": "只读查询，不转移个人道藏所有权",
            "order": 85,
        },
    },
)
async def show_cangjing(*, user_id: str, message: str, manager, **_) -> None:
    feature = current_game_services().features.zongmen_cangjing
    query = str(message or "").strip()
    try:
        page_number = _positive(query, "藏经阁页码") if query else 1
        value = await feature.page(user_id, page_number)
        await manager.send(
            reply.page(feature.copy(), value, feature.page_actions(value))
        )
    except CangjingFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


@GameCommand.command(
    cmd="借阅功法",
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "行动",
            "summary": "把藏经阁功法借入人物指定功法槽",
            "usage": ("借阅功法 编号或名称 槽位",),
            "side_effect": "替换指定人物功法槽；离开洞天后仍生效，离宗时恢复原功法",
            "order": 86,
        },
    },
)
async def borrow_technique(
    *, user_id: str, message: str, message_context, manager, **_
) -> None:
    feature = current_game_services().features.zongmen_cangjing
    parts = str(message or "").split()
    try:
        if len(parts) != 2:
            raise CangjingFeatureError("格式：借阅功法 编号或名称 槽位")
        value = await feature.borrow(
            user_id,
            message_context.request_id,
            parts[0],
            _positive(parts[1], "功法槽位"),
        )
        await manager.send(reply.borrowed(feature.copy(), value))
    except CangjingFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


def _positive(value: str, label: str) -> int:
    if not value.isdecimal() or int(value) < 1:
        raise CangjingFeatureError(f"{label}必须是正整数")
    return int(value)


__all__ = []
