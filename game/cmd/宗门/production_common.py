"""宗门灵脉、灵田命令。"""

from game.app import current_game_services
from game.features.zongmen_shengchan import SectProductionFeatureError

from . import production_reply as reply
from ..reply_composer import send_game_reply
from typing import Any


async def dispatch(
    kind: str, user_id: str, query: str, request_id: str, manager: Any
) -> None:
    feature = current_game_services().features.zongmen_shengchan
    try:
        entry = await feature.enter(kind, user_id, request_id, query)
    except SectProductionFeatureError as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc)))
        return
    if entry.kind == "view" and entry.view is not None:
        await send_game_reply(
            reply.viewed(
                feature.copy(), entry.view, feature.actions(entry.view)
            )
        )
    elif entry.kind == "started" and entry.result is not None:
        await send_game_reply(
            reply.started(
                feature.copy(),
                entry.result,
                feature.actions(entry.result.view),
            )
        )
    elif entry.kind == "collected" and entry.result is not None:
        await send_game_reply(
            reply.collected(
                feature.copy(),
                entry.result,
                feature.actions(entry.result.view),
            )
        )
    elif entry.kind == "terrains" and entry.view is not None:
        await send_game_reply(
            reply.terrains(
                feature.copy(), entry.view, feature.actions(entry.view)
            )
        )
    elif entry.kind == "placed" and entry.view is not None:
        await send_game_reply(
            reply.placed(
                feature.copy(), entry.view, feature.actions(entry.view)
            )
        )


__all__ = ["dispatch"]
