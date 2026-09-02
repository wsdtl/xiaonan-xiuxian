"""天道后台生命周期注册。"""

from __future__ import annotations

from launch import C, OnEvent, Scheduler, logger
from launch.message_events import subscribe_message_events, unsubscribe_message_events

from .console import service


@Scheduler.job("interval", minutes=30, id="cleanup_runtime_logs")
def cleanup_runtime_logs() -> None:
    """统一清理所有带到期时间的运行消息日志。"""

    service.cleanup()


@OnEvent.connect(priority=180)
async def start_heavenly_dao_console() -> None:
    if not service.auth.configured:
        logger.opt(colors=True).info(C.warn("天道后台未配置密码，消息服务保持关闭"))
        return
    await service.start()
    subscribe_message_events(service.handle_event)
    logger.opt(colors=True).info(C.ok("天道后台消息服务已启动"))


@OnEvent.disconnect(priority=180)
async def stop_heavenly_dao_console() -> None:
    unsubscribe_message_events(service.handle_event)
    await service.shutdown()
    logger.opt(colors=True).info(C.warn("天道后台消息服务已关闭"))


__all__ = []
