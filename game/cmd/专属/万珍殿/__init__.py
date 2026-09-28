"""宗门洞天专属万珍殿命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.zongmen_wanzhen import WanzhenFeatureError

from ...command import GameCommand
from . import reply
from launch.adapter import MessageContext
from typing import Any

_CATEGORIES = frozenset({"丹药", "真意", "气机", "器律", "阵法"})


@GameCommand.command(
    cmd="万珍殿",
    metadata={
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "行动",
            "summary": "在本宗洞天分类查看宗门成品",
            "usage": ("万珍殿", "万珍殿 丹药", "万珍殿 阵法 2"),
            "side_effect": "只读查询；成品由宗主统一发放",
            "order": 82,
        },
    },
)
async def show_wanzhen(user_id: str, message: str, manager: Any) -> None:
    feature = current_game_services().features.zongmen_wanzhen
    parts = str(message or "").split()
    try:
        if len(parts) > 2:
            raise WanzhenFeatureError("格式：万珍殿 [类别] [页码]")
        category = parts[0] if parts else "全部"
        page_number = _positive(parts[1], "万珍殿页码") if len(parts) == 2 else 1
        value = await feature.page(user_id, category, page_number)
        await manager.send(
            reply.page(feature.copy(), value, feature.page_actions(value))
        )
    except WanzhenFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


@GameCommand.command(
    cmd=("捐珍", "捐入万珍殿"),
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "行动",
            "summary": "将个人成品存入本宗万珍殿",
            "usage": (
                "捐入万珍殿 丹药/真意/气机 编号或名称 品级 数量",
                "捐入万珍殿 器律 编号或名称 数量",
                "捐入万珍殿 阵法 阵藏条目编号",
            ),
            "side_effect": "原子扣除个人成品并计入万珍殿；阵法每次存入一座",
            "order": 83,
        },
    },
)
async def donate_wanzhen(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.zongmen_wanzhen
    parts = str(message or "").split()
    try:
        if not parts or parts[0] not in _CATEGORIES:
            raise WanzhenFeatureError("格式：捐入万珍殿 类别 内容 ...")
        category = parts[0]
        if category == "阵法" and len(parts) == 2:
            identifier, grade_or_key, quantity = parts[1], parts[1], 1
        elif category == "器律" and len(parts) == 3:
            identifier, grade_or_key, quantity = (
                parts[1],
                "",
                _positive(parts[2], "数量"),
            )
        elif category in {"丹药", "真意", "气机"} and len(parts) == 4:
            identifier, grade_or_key, quantity = (
                parts[1],
                parts[2],
                _positive(parts[3], "数量"),
            )
        else:
            raise WanzhenFeatureError("万珍殿存入参数与类别不匹配")
        value = await feature.donate(
            user_id,
            message_context.request_id,
            category,
            identifier,
            grade_or_key,
            quantity,
        )
        await manager.send(reply.transferred(feature.copy(), value))
    except WanzhenFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


@GameCommand.command(
    cmd=("发珍", "发放万珍殿"),
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "行动",
            "summary": "由宗主向本宗成员发放万珍殿成品",
            "usage": (
                "发放万珍殿 角色名或编号 条目编号",
                "发放万珍殿 角色名或编号 条目编号 数量",
            ),
            "side_effect": "原子扣除宗门成品并写入目标成员的对应个人藏库",
            "order": 84,
        },
    },
)
async def grant_wanzhen(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.zongmen_wanzhen
    parts = str(message or "").split()
    try:
        if len(parts) not in {2, 3}:
            raise WanzhenFeatureError("格式：发放万珍殿 目标 条目编号 [数量]")
        quantity = _positive(parts[2], "数量") if len(parts) == 3 else 1
        value = await feature.grant(
            user_id,
            message_context.request_id,
            parts[0],
            parts[1],
            quantity,
        )
        await manager.send(reply.transferred(feature.copy(), value))
    except WanzhenFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


def _positive(value: str, label: str) -> int:
    if not value.isdecimal() or int(value) < 1:
        raise WanzhenFeatureError(f"{label}必须是正整数")
    return int(value)


__all__ = []
