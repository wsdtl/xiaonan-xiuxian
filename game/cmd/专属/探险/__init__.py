"""普通探险命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.tanxian import ExplorationFeatureError

from ...command import GameCommand, HelpSpec
from . import reply


@GameCommand.fullmatch(
    scope="专属",
    cmd="开始探险",
    aliases=("探险",),
    guard_rule="自主空闲",
    metadata={"hosting": {"activity": "探险", "phase": "start"}},
    help=HelpSpec(
        category="行动",
        summary="在当前地点开始一次普通探险",
        usage=("开始探险", "探险"),
        side_effect="预先完成全部战斗，扣除预计丹药并进入探险中",
        order=30,
    ),
)
async def start_exploration(*, user_id: str, message_context, manager, **_) -> None:
    feature = current_game_services().features.tanxian
    try:
        result = await feature.start(user_id, message_context.request_id)
        await manager.send(
            reply.started(feature.copy(), result, feature.start_actions())
        )
    except ExplorationFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


@GameCommand.fullmatch(
    scope="专属",
    cmd="探险进度",
    aliases=("查看探险进度", "探况"),
    guard_rule="已创建",
    help=HelpSpec(
        category="行动",
        summary="查看当前或最近一次探险已经解封的累计进度",
        usage=("查看探险进度", "探险进度"),
        side_effect="只读查询，不提前发放奖励",
        order=31,
    ),
)
async def exploration_progress(*, user_id: str, manager, **_) -> None:
    feature = current_game_services().features.tanxian
    try:
        result = await feature.progress(user_id)
        await manager.send(
            reply.progress(
                feature.copy(),
                result,
                feature.progress_actions(result.ended, result.can_settle),
            )
        )
    except ExplorationFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


@GameCommand.command(
    scope="专属",
    cmd="探险结束",
    aliases=("结算探险", "探险结算", "结束探险", "探结"),
    guard_rule="已创建",
    metadata={"hosting": {"activity": "探险", "phase": "end"}},
    help=HelpSpec(
        category="行动",
        summary="探险结束后结算全部结果并按页查看",
        usage=("结算探险", "结算探险 页码", "探险结算 页码", "结束探险 页码", "探险结束 页码"),
        side_effect="首次调用发放全部奖励并结束探险状态",
        order=32,
    ),
)
async def settle_exploration(
    *, user_id: str, message: str, message_context, manager, **_
) -> None:
    feature = current_game_services().features.tanxian
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
            raise ExplorationFeatureError(f"页码必须在1至{total_pages}之间")
        await manager.send(
            reply.settlement_page(
                feature.copy(),
                feature,
                result,
                page,
                feature.settlement_actions(page, total_pages),
            )
        )
    except ExplorationFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


__all__ = []
