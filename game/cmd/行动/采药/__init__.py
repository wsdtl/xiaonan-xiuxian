"""采药命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.caiyao import HerbGatheringFeatureError

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.fullmatch(
    cmd=("开始采药", "采药"),
    metadata={
        "hosting": {"activity": "采药", "phase": "start"},
        "scope": "通用",
        "guard_rule": "自主空闲且可行动",
        "help": {
            "category": "行动",
            "summary": "按当前地形与同行修士共同采集灵植",
            "usage": ("开始采药", "采药"),
            "side_effect": "锁定当前位置与参与者并预先确定六轮采药结果；参与者须同处地表，且当前地形要有灵植资源池",
            "order": 36,
        },
    },
)
async def start_herb_gathering(user_id: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.caiyao
    try:
        result = await feature.start(user_id, message_context.request_id)
        await send_game_reply(
            reply.started(feature.copy(), result, feature.started_actions())
        )
    except HerbGatheringFeatureError as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc), feature.format_actions()))


@GameCommand.fullmatch(
    cmd=("采药进度", "查看采药进度", "药况"),
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "查看当前或最近一次采药已完成的整轮所得",
            "usage": ("查看采药进度", "采药进度"),
            "side_effect": "只读查询，不提前写入纳戒",
            "order": 37,
        },
    },
)
async def herb_gathering_progress(user_id: str, manager: Any) -> None:
    feature = current_game_services().features.caiyao
    try:
        result = await feature.progress(user_id)
        await send_game_reply(
            reply.progress(
                feature.copy(),
                feature,
                result,
                feature.progress_actions(result.can_end),
            )
        )
    except HerbGatheringFeatureError as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc), feature.format_actions()))


@GameCommand.command(
    cmd=("采药结束", "结束采药", "收药"),
    metadata={
        "hosting": {"activity": "采药", "phase": "end"},
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "按完整轮次带领同行修士结束采药",
            "usage": ("结束采药", "结束采药 页码", "采药结束 页码"),
            "side_effect": "只有领队能结束；首次调用统一发放灵植并结束全体采药状态",
            "order": 38,
        },
    },
)
async def finish_herb_gathering(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.caiyao
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
        result = await feature.settle(user_id, message_context.request_id)
        total_pages = 1 + len(result.users)
        if page < 1 or page > total_pages:
            raise HerbGatheringFeatureError(f"页码必须在1至{total_pages}之间")
        await send_game_reply(
            reply.settlement_page(
                feature.copy(),
                feature,
                result,
                page,
                feature.settlement_actions(page, total_pages),
            )
        )
    except HerbGatheringFeatureError as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc), feature.format_actions()))



@GameCommand.command(
    cmd=("采药结果",),
    metadata={
        # 只读翻页：**故意不带 hosting 元数据**。托管中的玩法命令会被守卫拦下，手点的请求号
        # 与托管记录对不上就没反应（2026-10-14 全局排查后照探险同款修）。
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "查看采药结算结果的指定页（只读，不重复发奖）",
            "usage": ("采药结果", "采药结果 页码"),
            "side_effect": "只读查询；结算仍由结算命令在首次调用时完成",
            "order": 33,
        },
    },
)
async def show_herb_settlement(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    # 复用结算处理体（核心幂等：已结算只会回放，不重复发奖）。
    await finish_herb_gathering(user_id, message, message_context, manager)


__all__ = []
