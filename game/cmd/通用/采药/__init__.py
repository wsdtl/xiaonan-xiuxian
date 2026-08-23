"""采药命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.caiyao import HerbGatheringFeatureError

from ...command import GameCommand, HelpSpec
from . import reply


@GameCommand.fullmatch(
    scope="通用",
    cmd="开始采药",
    aliases=("采药",),
    guard_rule="自主空闲",
    metadata={"hosting": {"activity": "采药", "phase": "start"}},
    help=HelpSpec(
        category="行动",
        summary="按当前地形与同行修士共同采集灵植",
        usage=("开始采药", "采药"),
        side_effect="锁定当前位置与参与者并预先确定六轮采药结果",
        order=36,
    ),
)
async def start_herb_gathering(
    *, user_id: str, message_context, manager, **_
) -> None:
    feature = current_game_services().features.caiyao
    try:
        result = await feature.start(user_id, message_context.request_id)
        await manager.send(
            reply.started(feature.copy(), result, feature.started_actions())
        )
    except HerbGatheringFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


@GameCommand.fullmatch(
    scope="通用",
    cmd="采药进度",
    aliases=("查看采药进度", "药况"),
    guard_rule="已创建",
    help=HelpSpec(
        category="行动",
        summary="查看当前或最近一次采药已完成的整轮所得",
        usage=("查看采药进度", "采药进度"),
        side_effect="只读查询，不提前写入纳戒",
        order=37,
    ),
)
async def herb_gathering_progress(*, user_id: str, manager, **_) -> None:
    feature = current_game_services().features.caiyao
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
    except HerbGatheringFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


@GameCommand.command(
    scope="通用",
    cmd="采药结束",
    aliases=("结束采药", "收药"),
    guard_rule="已创建",
    metadata={"hosting": {"activity": "采药", "phase": "end"}},
    help=HelpSpec(
        category="行动",
        summary="按完整轮次带领同行修士结束采药",
        usage=("结束采药", "结束采药 页码", "采药结束 页码"),
        side_effect="首次调用统一发放灵植并结束全体采药状态",
        order=38,
    ),
)
async def finish_herb_gathering(
    *, user_id: str, message: str, message_context, manager, **_
) -> None:
    feature = current_game_services().features.caiyao
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
            raise HerbGatheringFeatureError(f"页码必须在1至{total_pages}之间")
        await manager.send(
            reply.settlement_page(
                feature.copy(),
                feature,
                result,
                page,
                feature.settlement_actions(page, total_pages),
            )
        )
    except HerbGatheringFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


__all__ = []
