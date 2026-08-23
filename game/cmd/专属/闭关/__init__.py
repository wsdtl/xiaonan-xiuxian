"""闭关命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.biguan import RetreatFeatureError

from ...command import GameCommand, HelpSpec
from . import reply


@GameCommand.fullmatch(
    scope="专属",
    cmd="开始闭关",
    aliases=("闭关",),
    guard_rule="自主空闲",
    metadata={"hosting": {"activity": "闭关", "phase": "start"}},
    help=HelpSpec(
        category="行动",
        summary="在当前地点与同行修士共同闭关",
        usage=("开始闭关", "闭关"),
        side_effect="锁定当前参与者并预先确定六轮闭关结果",
        order=33,
    ),
)
async def start_retreat(*, user_id: str, message_context, manager, **_) -> None:
    feature = current_game_services().features.biguan
    try:
        result = await feature.start(user_id, message_context.request_id)
        await manager.send(
            reply.started(feature.copy(), result, feature.started_actions())
        )
    except RetreatFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


@GameCommand.fullmatch(
    scope="专属",
    cmd="闭关进度",
    aliases=("查看闭关进度", "闭况"),
    guard_rule="已创建",
    help=HelpSpec(
        category="行动",
        summary="查看当前或最近一次闭关已经完成的整轮结果",
        usage=("查看闭关进度", "闭关进度"),
        side_effect="只读查询，不提前写入经验、恢复或功法",
        order=34,
    ),
)
async def retreat_progress(*, user_id: str, manager, **_) -> None:
    feature = current_game_services().features.biguan
    try:
        result = await feature.progress(user_id)
        await manager.send(
            reply.progress(
                feature.copy(),
                feature,
                result,
                feature.progress_actions(result.can_end),
            )
        )
    except RetreatFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


@GameCommand.command(
    scope="专属",
    cmd="闭关结束",
    aliases=("结束闭关", "出关",),
    guard_rule="已创建",
    metadata={"hosting": {"activity": "闭关", "phase": "end"}},
    help=HelpSpec(
        category="行动",
        summary="按已经完成的整轮结果带领全体出关",
        usage=("结束闭关", "结束闭关 页码", "出关 页码", "闭关结束 页码"),
        side_effect="首次调用统一发放结果并结束全体闭关状态",
        order=35,
    ),
)
async def end_retreat(
    *, user_id: str, message: str, message_context, manager, **_
) -> None:
    feature = current_game_services().features.biguan
    page_text = str(message or "").strip()
    try:
        page = 1 if not page_text else int(page_text)
    except ValueError:
        await manager.send(
            reply.error(feature.copy(), reply.text(feature.copy(), "错误", "格式"))
        )
        return
    try:
        result = await feature.settle(user_id, message_context.request_id)
        total_pages = 1 + len(result.users)
        if page < 1 or page > total_pages:
            raise RetreatFeatureError(f"页码必须在1至{total_pages}之间")
        await manager.send(
            reply.settlement_page(
                feature.copy(),
                feature,
                result,
                page,
                feature.settlement_actions(page, total_pages),
            )
        )
    except RetreatFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


__all__ = []
