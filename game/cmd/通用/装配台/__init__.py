"""装配台只提供整套方案入口、导入和清单公开开关。"""
from typing import Any

from game.app import current_game_services
from game.features.zhuangpei import ZhuangpeiFeatureError
from launch.adapter import MessageContext
from launch.paths import public_url

from ...command import GameCommand
from . import reply
from .site import router


@GameCommand.fullmatch(cmd="装配台", metadata={"scope": "通用", "guard_rule": "始终可用", "help": {"category": "修行", "summary": "打开公开的整套装配工具", "usage": ("装配台",), "side_effect": "只读", "order": 70}})
async def assembly(manager: Any) -> None:
    await manager.send(reply.entry(current_game_services().features.zhuangpei.copy(), public_url("assembly")))


@GameCommand.fullmatch(cmd="我的装配", metadata={"scope": "通用", "guard_rule": "已创建", "help": {"category": "修行", "summary": "查看当前整套装配及装配码", "usage": ("我的装配",), "side_effect": "只读", "order": 71}})
async def my_assembly(user_id: str, manager: Any) -> None:
    feature = current_game_services().features.zhuangpei
    try:
        await manager.send(reply.scheme(feature.copy()["当前"], await feature.current(user_id)))
    except ZhuangpeiFeatureError as exc:
        await manager.send(reply.error(str(exc)))


@GameCommand.command(cmd="导入装配", metadata={"scope": "通用", "guard_rule": "自主空闲或休息", "help": {"category": "修行", "summary": "校验并一次性导入整套装配", "usage": ("导入装配 装配码",), "side_effect": "替换整套装配，按规则消耗库存；空槽清除原装配", "order": 72}})
async def import_assembly(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.zhuangpei
    try:
        parts = message.split()
        if len(parts) != 1:
            raise ZhuangpeiFeatureError("格式：导入装配 装配码")
        value = await feature.import_code(user_id, message_context.request_id, parts[0])
        await manager.send(reply.scheme(feature.copy()["成功"], value))
    except ZhuangpeiFeatureError as exc:
        await manager.send(reply.error(str(exc), "可发送「我的装配」查看当前装配与最新装配码。"))


@GameCommand.fullmatch(cmd="公开池", metadata={"scope": "通用", "guard_rule": "已创建", "help": {"category": "修行", "summary": "开关自己的拥有清单公开展示", "usage": ("公开池",), "side_effect": "切换清单公开状态，默认关闭", "order": 73}})
async def toggle_public(user_id: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.zhuangpei
    try:
        enabled = await feature.toggle_public(user_id, message_context.request_id)
        await manager.send(reply.notice(feature.copy()["已公开" if enabled else "已关闭"]))
    except ZhuangpeiFeatureError as exc:
        await manager.send(reply.error(str(exc)))


__all__ = ["router"]
