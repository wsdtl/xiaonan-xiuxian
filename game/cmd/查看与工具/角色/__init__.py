"""角色二级组件命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.chakan_juese import CharacterOverviewError
from game.features.chuangjian_renwu import (
    CharacterExistsError,
    CreateCharacterFormatError,
    InvalidCreateCharacterError,
)

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd=("创建人物", "创建角色"),
    metadata={
        "scope": "通用",
        "guard_rule": "仅未创建",
        "help": {
            "category": "查看与工具",
            "summary": "建立当前账号的唯一修士人物",
            "usage": ("创建人物 云中鹤 男", "创建人物 姓名 性别 [种族]"),
            "side_effect": "每个账号只能创建一个人物；姓名须 2–12 个汉字、字母或数字，种族可省略（默认人族）",
            "order": 10,
        },
    },
)
async def create_character(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    try:
        result = await current_game_services().features.chuangjian_renwu.create_from_text(
            user_id, message_context.request_id, message
        )
    except CreateCharacterFormatError:
        await send_game_reply(reply.invalid_create_format())
        return
    except InvalidCreateCharacterError as exc:
        await send_game_reply(reply.create_error(str(exc)))
        return
    except CharacterExistsError:
        await send_game_reply(reply.character_exists())
        return
    await send_game_reply(reply.created(result, result.altitude_unit))


@GameCommand.fullmatch(
    cmd=("人物", "角色", "我的存档", "存档"),
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "查看与工具",
            "summary": "查看当前人物的修为、状态、位置与已有构筑",
            "usage": ("人物", "角色", "我的存档", "存档"),
            "side_effect": "只查看，不会改变人物状态",
            "order": 20,
        },
    },
)
async def show_character(user_id: str, manager: Any) -> None:
    try:
        result = await current_game_services().features.chakan_juese.inspect(user_id)
    except CharacterOverviewError:
        await send_game_reply(reply.overview_error())
        return
    xuemai = current_game_services().features.xuemai
    dna = await xuemai.dna(user_id)
    await send_game_reply(
        reply.overview(
            result,
            result.altitude_unit,
            dna=dna,
            bloodlines=xuemai.bloodlines(dna),
        )
    )


__all__ = []