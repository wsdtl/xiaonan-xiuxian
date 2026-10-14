"""闭关命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.biguan import RetreatFeatureError

from ...command import GameCommand
from . import reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.fullmatch(
    cmd=("开始闭关", "闭关"),
    metadata={
        "hosting": {"activity": "闭关", "phase": "start"},
        "scope": "专属",
        "guard_rule": "自主空闲",
        "help": {
            "category": "行动",
            "summary": "在当前地点与同行修士共同闭关",
            "usage": ("开始闭关", "闭关"),
            "side_effect": "锁定当前参与者并预先确定六轮闭关结果",
            "order": 33,
        },
    },
)
async def start_retreat(user_id: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.biguan
    try:
        result = await feature.start(user_id, message_context.request_id)
        await manager.send(
            reply.started(feature.copy(), result, feature.started_actions())
        )
    except RetreatFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc), feature.format_actions()))


@GameCommand.fullmatch(
    cmd=("闭关进度", "查看闭关进度", "闭况"),
    metadata={
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "查看当前或最近一次闭关已经完成的整轮结果",
            "usage": ("查看闭关进度", "闭关进度"),
            "side_effect": "只读查询，不提前写入经验、恢复或功法",
            "order": 34,
        },
    },
)
async def retreat_progress(user_id: str, manager: Any) -> None:
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
        await manager.send(reply.error(feature.copy(), str(exc), feature.format_actions()))


@GameCommand.command(
    cmd=("闭关结束", "结束闭关", "出关"),
    metadata={
        "hosting": {"activity": "闭关", "phase": "end"},
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "按已经完成的整轮结果带领全体出关",
            "usage": ("结束闭关", "结束闭关 页码", "出关 页码", "闭关结束 页码"),
            "side_effect": "首次调用统一发放结果并结束全体闭关状态",
            "order": 35,
        },
    },
)
async def end_retreat(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.biguan
    page_text = str(message or "").strip()
    try:
        page = 1 if not page_text else int(page_text)
    except ValueError:
        await manager.send(
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
        await manager.send(reply.error(feature.copy(), str(exc), feature.format_actions()))



@GameCommand.command(
    cmd=("闭关结果",),
    metadata={
        # 只读翻页：**故意不带 hosting 元数据**。托管中的玩法命令会被守卫拦下，手点的请求号
        # 与托管记录对不上就没反应（2026-10-14 全局排查后照探险同款修）。
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "查看闭关结算结果的指定页（只读，不重复发奖）",
            "usage": ("闭关结果", "闭关结果 页码"),
            "side_effect": "只读查询；结算仍由结算命令在首次调用时完成",
            "order": 33,
        },
    },
)
async def show_retreat_settlement(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    # 复用结算处理体（核心幂等：已结算只会回放，不重复发奖）。
    await end_retreat(user_id, message, message_context, manager)


__all__ = []
