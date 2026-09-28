"""宗门灵脉、灵田命令。"""

from game.app import current_game_services
from game.features.zongmen_shengchan import SectProductionFeatureError

from ...command import GameCommand
from . import reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd="灵脉",
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "行动",
            "summary": "查看或收取本宗灵脉的随机灵石与灵矿",
            "usage": ("灵脉", "灵脉 开启", "灵脉 收取"),
            "side_effect": "查看只读；收取时按完整生产轮次统一写入本宗灵藏",
            "order": 82,
        },
    },
)
async def lingmai(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    await _dispatch(
        "灵脉", user_id, str(message or "").strip(), message_context.request_id, manager
    )


@GameCommand.command(
    cmd="灵田",
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "行动",
            "summary": "查看或收取本宗灵田的随机灵植，并可选定一处地形",
            "usage": (
                "灵田",
                "灵田 开启",
                "灵田 收取",
                "灵田 选地形",
                "灵田 选地形 地形名",
                "灵田 清地形",
            ),
            "side_effect": (
                "查看只读；选定地形后灵田只产该地形的灵植，收取时按完整生产轮次"
                "统一写入本宗灵藏"
            ),
            "order": 83,
        },
    },
)
async def lingtian(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    await _dispatch(
        "灵田", user_id, str(message or "").strip(), message_context.request_id, manager
    )


async def _dispatch(
    kind: str, user_id: str, query: str, request_id: str, manager: Any
) -> None:
    feature = current_game_services().features.zongmen_shengchan
    try:
        args = query.split()
        if not args:
            value = await feature.view(kind, user_id)
            await manager.send(
                reply.viewed(feature.copy(), value, feature.actions(value))
            )
            return
        if args == ["开启"]:
            value = await feature.start(kind, user_id, request_id)
            await manager.send(
                reply.started(feature.copy(), value, feature.actions(value.view))
            )
            return
        if args == ["收取"]:
            value = await feature.collect(kind, user_id, request_id)
            await manager.send(
                reply.collected(feature.copy(), value, feature.actions(value.view))
            )
            return
        if kind == "灵田" and args[0] == "选地形" and len(args) <= 2:
            if len(args) == 1:
                value = await feature.view(kind, user_id)
                await manager.send(
                    reply.terrains(feature.copy(), value, feature.actions(value))
                )
                return
            value = await feature.select_terrain(kind, user_id, request_id, args[1])
            await manager.send(
                reply.placed(feature.copy(), value, feature.actions(value))
            )
            return
        if kind == "灵田" and args == ["清地形"]:
            value = await feature.clear_terrain(kind, user_id, request_id)
            await manager.send(
                reply.placed(feature.copy(), value, feature.actions(value))
            )
            return
        raise SectProductionFeatureError(f"格式：{_usage(kind)}")
    except SectProductionFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


def _usage(kind: str) -> str:
    if kind == "灵田":
        return (
            "灵田、灵田 开启、灵田 收取、灵田 选地形 [地形名] 或 灵田 清地形"
        )
    return f"{kind}、{kind} 开启 或 {kind} 收取"


__all__ = []
