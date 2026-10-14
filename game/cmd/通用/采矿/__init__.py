"""采矿命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.caikuang import OreGatheringFeatureError

from ...command import GameCommand
from . import reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.fullmatch(
    cmd=("开始采矿", "采矿"),
    metadata={
        "hosting": {"activity": "采矿", "phase": "start"},
        "scope": "通用",
        "guard_rule": "自主空闲且可行动",
        "help": {
            "category": "行动",
            "summary": "按当前地形与同行修士共同采集灵矿",
            "usage": ("开始采矿", "采矿"),
            "side_effect": "锁定当前位置与参与者并预先确定六轮采矿结果；参与者须同处地表，且当前地形要有灵矿资源池",
            "order": 39,
        },
    },
)
async def start_ore_gathering(user_id: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.caikuang
    try:
        result = await feature.start(user_id, message_context.request_id)
        await manager.send(
            reply.started(feature.copy(), result, feature.started_actions())
        )
    except OreGatheringFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc), feature.format_actions()))


@GameCommand.fullmatch(
    cmd=("采矿进度", "查看采矿进度", "矿况"),
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "查看当前或最近一次采矿已完成的整轮所得",
            "usage": ("查看采矿进度", "采矿进度"),
            "side_effect": "只读查询，不提前写入纳戒",
            "order": 40,
        },
    },
)
async def ore_gathering_progress(user_id: str, manager: Any) -> None:
    feature = current_game_services().features.caikuang
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
    except OreGatheringFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc), feature.format_actions()))


@GameCommand.command(
    cmd=("采矿结束", "结束采矿", "收矿"),
    metadata={
        "hosting": {"activity": "采矿", "phase": "end"},
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "按完整轮次带领同行修士结束采矿",
            "usage": ("结束采矿", "结束采矿 页码", "采矿结束 页码"),
            "side_effect": "只有领队能结束；首次调用统一发放灵矿并结束全体采矿状态",
            "order": 41,
        },
    },
)
async def finish_ore_gathering(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.caikuang
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
            raise OreGatheringFeatureError(f"页码必须在1至{total_pages}之间")
        await manager.send(
            reply.settlement_page(
                feature.copy(),
                feature,
                result,
                page,
                feature.settlement_actions(page, total_pages),
            )
        )
    except OreGatheringFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc), feature.format_actions()))



@GameCommand.command(
    cmd=("采矿结果",),
    metadata={
        # 只读翻页：**故意不带 hosting 元数据**。托管中的玩法命令会被守卫拦下，手点的请求号
        # 与托管记录对不上就没反应（2026-10-14 全局排查后照探险同款修）。
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "查看采矿结算结果的指定页（只读，不重复发奖）",
            "usage": ("采矿结果", "采矿结果 页码"),
            "side_effect": "只读查询；结算仍由结算命令在首次调用时完成",
            "order": 33,
        },
    },
)
async def show_ore_settlement(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    # 复用结算处理体（核心幂等：已结算只会回放，不重复发奖）。
    await finish_ore_gathering(user_id, message, message_context, manager)


__all__ = []
