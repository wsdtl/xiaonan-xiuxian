"""天道后台命令与受保护的管理台路由。"""

from __future__ import annotations

from launch.paths import public_url

from ...command import GameCommand
from . import reply
from . import runtime as runtime
from .site import router


@GameCommand.fullmatch(
    cmd="天道后台",
    metadata={"scope": "后台", "guard_rule": "始终可用", "hidden": True},
)
async def heavenly_dao_console(*, manager) -> None:
    await manager.send(reply.entry(public_url("game-console")))


__all__ = ["router"]
