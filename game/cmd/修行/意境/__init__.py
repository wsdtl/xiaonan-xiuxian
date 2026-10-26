"""意境二级组件命令。"""

from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.yijing import YijingError
from launch.adapter import MessageContext

from ...command import GameCommand
from . import reply
from .site import router
from ...reply_composer import send_game_reply


@GameCommand.command(
    cmd=("意境",),
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "修行",
            "summary": "查看与修习意境（六条路各自记阶、道行共享）",
            "side_effect": (
                "查看只读；点阶消耗道行，六条路各自受当前境界给的阶上限约束（最高第 9 阶），"
                "投进去的道行不退（洗点见忘境丹）"
            ),
            "usage": ("意境", "意境 点 不尽长江意境", "意境 点 <路名或编号>"),
            "order": 20,
        },
    },
)
async def yijing(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    """`意境` 看六条路各自的阶；`意境 点 <路名或编号>` 给那一条路点一阶。"""

    feature = current_game_services().features.yijing
    parts = message.split()
    try:
        if parts and parts[0] == "点" and len(parts) == 2:
            view = await feature.inspect(user_id)
            wanted = parts[1]
            content_id = next(
                (
                    route.content_id
                    for route in view.routes
                    if route.content_id == wanted or route.name == wanted
                ),
                "",
            )
            if not content_id:
                await send_game_reply(reply.yijing_refused(f"没有叫「{wanted}」的意境"))
                return
            view = await feature.point(user_id, message_context.request_id, content_id)
            await send_game_reply(reply.yijing_pointed(view, content_id))
        else:
            await send_game_reply(reply.yijing_view(await feature.inspect(user_id)))
    except YijingError as exc:
        await send_game_reply(reply.yijing_refused(str(exc)))


__all__ = ["router"]
