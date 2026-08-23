"""即时行路命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.xinglu import (
    TravelConflictError,
    TravelQueryError,
    TravelRequest,
)

from ...command import GameCommand, HelpSpec
from . import reply


@GameCommand.command(
    scope="通用",
    cmd="去",
    aliases=("前往",),
    guard_rule="自主空闲",
    help=HelpSpec(
        category="行动",
        summary="前往指定地点或坐标并立即抵达",
        usage=("去 地点名", "去 x y"),
        side_effect="立即改变人物位置，不产生行路等待时间",
        order=10,
    ),
)
async def travel(
    *,
    user_id: str,
    message: str,
    message_context,
    manager,
) -> None:
    destination = str(message or "").strip()
    if not destination:
        await manager.send(reply.missing_destination())
        return
    services = current_game_services()
    try:
        result = await services.features.xinglu.travel(
            TravelRequest(
                user_id=user_id,
                request_id=message_context.request_id,
                destination=destination,
            )
        )
    except TravelQueryError as exc:
        await manager.send(reply.query_error(str(exc)))
        return
    except TravelConflictError:
        await manager.send(reply.conflict())
        return
    position = services.features.weizhi
    functions = position.open_location_functions(
        result.plan.destination.available_functions
    )
    await manager.send(
        reply.success(
            result,
            functions,
            position.position_actions(
                functions,
                plant_pool=result.plan.destination.plant_pool,
                mineral_pool=result.plan.destination.mineral_pool,
            ),
        )
    )


__all__ = []
