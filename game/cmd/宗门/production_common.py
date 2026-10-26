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
        args = query.split()
        if not args:
            value = await feature.view(kind, user_id)
            await send_game_reply(
                reply.viewed(feature.copy(), value, feature.actions(value))
            )
            return
        if args == ["开启"]:
            value = await feature.start(kind, user_id, request_id)
            await send_game_reply(
                reply.started(feature.copy(), value, feature.actions(value.view))
            )
            return
        if args == ["收取"]:
            value = await feature.collect(kind, user_id, request_id)
            await send_game_reply(
                reply.collected(feature.copy(), value, feature.actions(value.view))
            )
            return
        if kind == "灵田" and args[0] == "选地形" and len(args) <= 2:
            if len(args) == 1:
                value = await feature.view(kind, user_id)
                await send_game_reply(
                    reply.terrains(feature.copy(), value, feature.actions(value))
                )
                return
            value = await feature.select_terrain(kind, user_id, request_id, args[1])
            await send_game_reply(
                reply.placed(feature.copy(), value, feature.actions(value))
            )
            return
        if kind == "灵田" and args == ["清地形"]:
            value = await feature.clear_terrain(kind, user_id, request_id)
            await send_game_reply(
                reply.placed(feature.copy(), value, feature.actions(value))
            )
            return
        raise SectProductionFeatureError(f"格式：{_usage(kind)}")
    except SectProductionFeatureError as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc)))


def _usage(kind: str) -> str:
    if kind == "灵田":
        return (
            "灵田、灵田 开启、灵田 收取、灵田 选地形 [地形名] 或 灵田 清地形"
        )
    return f"{kind}、{kind} 开启 或 {kind} 收取"


__all__ = ["dispatch"]
