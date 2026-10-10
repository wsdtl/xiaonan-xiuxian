"""角色二级组件命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.yijing import YijingError
from game.features.chakan_juese import CharacterOverviewError
from game.features.chuangjian_renwu import (
    CharacterExistsError,
    CreateCharacterRequest,
    InvalidCreateCharacterError,
)

from ...command import GameCommand
from . import reply
from launch.adapter import MessageContext
from typing import Any


@GameCommand.command(
    cmd=("创建人物", "创建角色"),
    metadata={
        "scope": "通用",
        "guard_rule": "仅未创建",
        "help": {
            "category": "角色",
            "summary": "建立当前账号的唯一修士人物",
            "usage": ("创建人物 姓名 性别 [种族]",),
            "side_effect": "每个账号只能创建一个人物",
            "order": 10,
        },
    },
)
async def create_character(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    parts = message.split()
    if len(parts) not in (2, 3):
        await manager.send(reply.invalid_create_format())
        return
    name, gender = parts[0], parts[1]
    race = parts[2] if len(parts) == 3 else ""
    try:
        result = await current_game_services().features.chuangjian_renwu.create(
            CreateCharacterRequest(
                user_id=user_id,
                request_id=message_context.request_id,
                name=name,
                gender=gender,
                race=race,
            )
        )
    except InvalidCreateCharacterError as exc:
        await manager.send(reply.create_error(str(exc)))
        return
    except CharacterExistsError:
        await manager.send(reply.character_exists())
        return
    await manager.send(reply.created(result))


@GameCommand.fullmatch(
    cmd=("人物", "角色"),
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "角色",
            "summary": "查看当前人物的修为、状态、位置与已有构筑",
            "usage": ("人物",),
            "side_effect": "只查看，不会改变人物状态",
            "order": 20,
        },
    },
)
async def show_character(user_id: str, manager: Any) -> None:
    try:
        result = await current_game_services().features.chakan_juese.inspect(user_id)
    except CharacterOverviewError:
        await manager.send(reply.overview_error())
        return
    await manager.send(reply.overview(result))


__all__ = []


@GameCommand.command(
    cmd=("意境",),
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "角色",
            "summary": "查看与修习意境",
            "usage": ("意境", "意境 升", "意境 修 <路名>"),
            "order": 20,
        },
    },
)
async def yijing(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    """`意境` 看；`意境 升` 花道行升一阶；`意境 修 <路名>` 选修一条路。"""

    feature = current_game_services().features.yijing
    parts = message.split()
    try:
        if parts and parts[0] == "升":
            view = await feature.upgrade(user_id, message_context.request_id)
            await manager.send(reply.yijing_upgraded(view))
        elif parts and parts[0] == "修" and len(parts) == 2:
            current = await feature.inspect(user_id)
            wanted = parts[1]
            content_id = next(
                (cid for cid, name in current.routes if name == wanted), ""
            )
            if not content_id:
                await manager.send(reply.yijing_refused(f"没有叫「{wanted}」的意境"))
                return
            view = await feature.choose(user_id, message_context.request_id, content_id)
            await manager.send(reply.yijing_view(view))
        else:
            await manager.send(reply.yijing_view(await feature.inspect(user_id)))
    except YijingError as exc:
        await manager.send(reply.yijing_refused(str(exc)))
