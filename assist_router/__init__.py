"""辅助路由：框架事件总线 -> 独立身份映射库。

本包只消费框架的官方 QQ 入站事件并连接 NapCat；游戏业务暂不读取它。
"""

from __future__ import annotations

from launch import C, logger
from launch.adapter.identity import register_identity_resolver
from launch.on_event import OnEvent

from .api import bind, router
from .service import AssistRouterService

service = AssistRouterService()
bind(service)


def _resolve_user(bot_key: str, openid: str) -> str:
    try:
        route = service.resolve_user(bot_key=bot_key, openid=openid)
    except Exception:  # noqa: BLE001 - 解析失败不能拖垮 QQ 命令
        return ""
    return str(route.get("qq_uin") or "") if route else ""


def _resolve_group(bot_key: str, group_openid: str) -> str:
    try:
        route = service.resolve_group(bot_key=bot_key, group_openid=group_openid)
    except Exception:  # noqa: BLE001 - 解析失败不能拖垮 QQ 命令
        return ""
    return str(route.get("qq_group_id") or "") if route else ""


register_identity_resolver(user=_resolve_user, group=_resolve_group)


@OnEvent.connect(priority=0)
def _start_assist_router() -> None:
    try:
        service.start()
    except Exception:  # noqa: BLE001 - 辅助路由失败不能拖垮主服务
        logger.opt(colors=True).exception(
            C.join(C.warn("辅助路由启动失败，主服务继续运行"))
        )


@OnEvent.disconnect(priority=0)
async def _stop_assist_router() -> None:
    await service.stop()


__all__ = ["router", "service"]
