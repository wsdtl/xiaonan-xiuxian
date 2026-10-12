"""意境二级组件命令。"""

from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.yijing import YijingError
from launch.adapter import MessageContext

from ...command import GameCommand
from . import reply


@GameCommand.command(
    cmd=("意境",),
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "角色",
            "summary": "查看与修习意境",
        "side_effect": "查看只读；升阶消耗道行且受当前境界给的阶上限约束（最高第 9 阶），改路会把已练的阶清零",
            "usage": ("意境", "意境 升", "意境 修 <路名>"),
            "order": 20,
        },
    },
)
async def yijing(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    """`意境` 看；`意境 升` 花道行升一阶；`意境 修 <路名>` 选修一条路。"""

    feature = current_game_services().features.yijing
    parts = message.split()
    try:
        if parts and parts[0] == "升":
            view = await feature.upgrade(user_id, message_context.request_id)
            await manager.send(reply.yijing_upgraded(view))
        elif parts and parts[0] == "修" and len(parts) == 2:
            current = await feature.inspect(user_id)
            wanted = parts[1]
            content_id = next((cid for cid, name in current.routes if name == wanted), "")
            if not content_id:
                await manager.send(reply.yijing_refused(f"没有叫「{wanted}」的意境"))
                return
            view = await feature.choose(user_id, message_context.request_id, content_id)
            await manager.send(reply.yijing_view(view))
        else:
            await manager.send(reply.yijing_view(await feature.inspect(user_id)))
    except YijingError as exc:
        await manager.send(reply.yijing_refused(str(exc)))
