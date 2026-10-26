"""普通探险命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.tanxian import ExplorationFeatureError

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.fullmatch(
    cmd=("开始探险", "探险"),
    metadata={
        "hosting": {"activity": "探险", "phase": "start"},
        "scope": "专属",
        "guard_rule": "自主空闲且可行动",
        "help": {
            "category": "行动",
            "summary": "在当前地点开始一次普通探险",
            "usage": ("开始探险", "探险"),
            "side_effect": "预先完成全部战斗，扣除预计丹药并进入探险中",
            "order": 30,
        },
    },
)
async def start_exploration(user_id: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.tanxian
    try:
        result = await feature.start(user_id, message_context.request_id)
        await send_game_reply(
            reply.started(feature.copy(), result, feature.start_actions())
        )
    except ExplorationFeatureError as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc), feature.format_actions()))


@GameCommand.fullmatch(
    cmd=("探险进度", "查看探险进度", "探况"),
    metadata={
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "查看当前或最近一次探险已经解封的累计进度",
            "usage": ("查看探险进度", "探险进度"),
            "side_effect": "只读查询，不提前发放奖励",
            "order": 31,
        },
    },
)
async def exploration_progress(user_id: str, manager: Any) -> None:
    feature = current_game_services().features.tanxian
    try:
        result = await feature.progress(user_id)
        await send_game_reply(
            reply.progress(
                feature.copy(),
                result,
                feature.progress_actions(result.ended, result.can_settle),
            )
        )
    except ExplorationFeatureError as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc), feature.format_actions()))


async def _settle_and_show(
    user_id: str, message: str, request_id: str, manager: Any
) -> None:
    """结算一次（核心幂等：已结算就回放旧结果）并把指定页回给玩家。"""

    feature = current_game_services().features.tanxian
    page_text = str(message or "").strip()
    try:
        page = 1 if not page_text else int(page_text)
    except ValueError:
        await send_game_reply(
            reply.error(
                feature.copy(),
                reply.text(feature.copy(), "错误", "写法"),
                feature.format_actions(),
            )
        )
        return
    try:
        result = await feature.settle(user_id, request_id)
        total_pages = 1 + len(result.users)
        if page < 1 or page > total_pages:
            raise ExplorationFeatureError(f"页码必须在1至{total_pages}之间")
        await send_game_reply(
            reply.settlement_page(
                feature.copy(),
                feature,
                result,
                page,
                feature.settlement_actions(page, total_pages),
            )
        )
    except ExplorationFeatureError as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc), feature.format_actions()))


@GameCommand.command(
    cmd=("探险结束", "结算探险", "探险结算", "结束探险", "探结"),
    metadata={
        "hosting": {"activity": "探险", "phase": "end"},
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "探险结束后由领队结算全部结果并按页查看",
            "usage": (
                "结算探险",
                "结算探险 页码",
                "探险结算 页码",
                "结束探险 页码",
                "探险结束 页码",
            ),
            "side_effect": "首次调用发放全部奖励并结束探险状态",
            "order": 32,
        },
    },
)
async def settle_exploration(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    await _settle_and_show(user_id, message, message_context.request_id, manager)


@GameCommand.command(
    cmd=("探险结果", "查看探险", "探险结算页"),
    metadata={
        # 只读翻页：**故意不带 hosting 元数据**。托管中的玩法命令会被守卫拦下，而手点
        # 「下一页」的请求号是新的、与托管记录对不上，于是点了没反应（2026-10-14 实修）。
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "查看探险结算结果的指定页（只读，不重复发奖）",
            "usage": ("探险结果", "探险结果 页码"),
            "side_effect": "只读查询；结算仍由「结算探险」在首次调用时完成",
            "order": 33,
        },
    },
)
async def show_settlement_page(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    await _settle_and_show(user_id, message, message_context.request_id, manager)


__all__ = []
