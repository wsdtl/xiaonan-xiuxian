"""宗门洞天专属灵藏命令。"""
from __future__ import annotations

from game.app import current_game_services
from game.features.presentation import ItemRefError, parse_item_ref
from game.features.zongmen_lingcang import LingcangFeatureError

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any

_CATEGORIES = frozenset({"灵植", "灵矿", "兽宝"})


@GameCommand.command(
    cmd="灵藏",
    metadata={
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "宗门",
            "summary": "在宗门园区灵藏查看宗门基础资源，或向本宗捐入材料",
            "usage": (
                "灵藏",
                "灵藏 灵植",
                "灵藏 灵矿 2",
                "灵藏 捐入 灵石 100",
                "灵藏 捐入 灵植 黄品云参 3",
            ),
            "side_effect": "只读查看；捐入扣个人资源、计入宗门灵藏，取用只发生在炼制与产出结算",
            "order": 80,
        },
    },
)
async def lingcang(
    user_id: str, message: str, message_context: MessageContext, manager: Any
) -> None:
    feature = current_game_services().features.zongmen_lingcang
    parts = str(message or "").split()
    try:
        if parts and parts[0] == "捐入":
            await _donate(feature, user_id, parts[1:], message_context, manager)
            return
        if len(parts) > 2:
            raise LingcangFeatureError("格式：灵藏 [灵植/灵矿/兽宝] [页码]")
        category = parts[0] if parts else "全部"
        page_number = _positive(parts[1], "灵藏页码") if len(parts) == 2 else 1
        value = await feature.page(user_id, category, page_number)
        await send_game_reply(
            reply.page(feature.copy(), value, feature.page_actions(value))
        )
    except (LingcangFeatureError, ItemRefError) as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc)))


async def _donate(
    feature: Any,
    user_id: str,
    parts: list[str],
    message_context: MessageContext,
    manager: Any,
) -> None:
    try:
        if len(parts) == 2 and parts[0] == "灵石":
            quantity = _positive(parts[1], "灵石数量")
            result = await feature.donate_stones(
                user_id, message_context.request_id, quantity
            )
            await send_game_reply(reply.donated_stones(feature.copy(), quantity, result))
            return
        if len(parts) not in {3, 4} or parts[0] not in _CATEGORIES:
            raise LingcangFeatureError("格式：灵藏 捐入 类别 <品级><物品> 数量")
        if len(parts) == 4:
            item, grade = parts[1], parts[2]
        else:
            ref = parse_item_ref(parts[1])
            item, grade = ref.item, ref.grade
        result = await feature.donate_material(
            user_id,
            message_context.request_id,
            parts[0],
            item,
            grade,
            _positive(parts[-1], "捐献数量"),
        )
        await send_game_reply(reply.donated_material(feature.copy(), result))
    except (LingcangFeatureError, ItemRefError) as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc)))


def _positive(value: str, label: str) -> int:
    if not value.isdecimal() or int(value) < 1:
        raise LingcangFeatureError(f"{label}必须是正整数")
    return int(value)


__all__ = []
