"""宗门灵脉、灵田命令。"""

from game.app import current_game_services
from game.features.zongmen_shengchan import SectProductionFeatureError

from ...command import GameCommand, HelpSpec
from . import reply


@GameCommand.command(
    scope="专属",
    cmd="灵脉",
    guard_rule="自主空闲或休息",
    help=HelpSpec(
        category="行动",
        summary="查看或收取本宗灵脉的随机灵石与灵矿",
        usage=("灵脉", "灵脉 开启", "灵脉 收取"),
        side_effect="查看只读；收取时按完整生产轮次统一写入本宗灵藏",
        order=82,
    ),
)
async def lingmai(*, user_id: str, message: str, message_context, manager, **_) -> None:
    await _dispatch(
        "灵脉", user_id, str(message or "").strip(), message_context.request_id, manager
    )


@GameCommand.command(
    scope="专属",
    cmd="灵田",
    guard_rule="自主空闲或休息",
    help=HelpSpec(
        category="行动",
        summary="查看或收取本宗灵田的随机灵植",
        usage=("灵田", "灵田 开启", "灵田 收取"),
        side_effect="查看只读；收取时按完整生产轮次统一写入本宗灵藏",
        order=83,
    ),
)
async def lingtian(
    *, user_id: str, message: str, message_context, manager, **_
) -> None:
    await _dispatch(
        "灵田", user_id, str(message or "").strip(), message_context.request_id, manager
    )


async def _dispatch(
    kind: str, user_id: str, query: str, request_id: str, manager
) -> None:
    feature = current_game_services().features.zongmen_shengchan
    try:
        if query not in {"", "开启", "收取"}:
            raise SectProductionFeatureError(
                f"格式：{kind}、{kind} 开启 或 {kind} 收取"
            )
        if query == "开启":
            value = await feature.start(kind, user_id, request_id)
            await manager.send(
                reply.started(feature.copy(), value, feature.actions(value.view))
            )
            return
        if query == "收取":
            value = await feature.collect(kind, user_id, request_id)
            await manager.send(
                reply.collected(feature.copy(), value, feature.actions(value.view))
            )
            return
        value = await feature.view(kind, user_id)
        await manager.send(reply.viewed(feature.copy(), value, feature.actions(value)))
    except SectProductionFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


__all__ = []
