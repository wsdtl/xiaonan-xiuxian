"""晓楠修仙 HTTP 服务入口。"""

from __future__ import annotations

import asyncio
import sys

import uvicorn
from fastapi import FastAPI

from launch import (
    LOGGING_CONFIG,
    FastAPIAllowed,
    FastAPIIncludeRouter,
    config,
    lifespan,
)


def configure_windows_event_loop() -> None:
    if sys.platform != "win32":
        return
    policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy is not None:
        asyncio.set_event_loop_policy(policy())


def create_app() -> FastAPI:
    """加载命令模块，挂载消息驱动器并创建应用。"""

    app = FastAPI(
        title=config.project.name,
        debug=config.project.debug,
        lifespan=lifespan,
    )
    FastAPIAllowed(app)
    FastAPIIncludeRouter(app)
    return app


def uvicorn_ssl_kwargs() -> dict[str, str]:
    if not config.server.ssl_certfile or not config.server.ssl_keyfile:
        return {}
    return {
        "ssl_certfile": str(config.server.ssl_certfile),
        "ssl_keyfile": str(config.server.ssl_keyfile),
    }


if __name__ == "__main__":
    configure_windows_event_loop()
    uvicorn.run(
        app="main:create_app",
        factory=True,
        host=config.server.host,
        port=config.server.port,
        reload=config.server.reload,
        log_config=LOGGING_CONFIG,
        # 优雅关闭最多等 5 秒：天道后台挂着流式连接时，默认会一直等下去（日志里的
        # "Waiting for connections to close"），到点由 uvicorn 直接收摊。
        timeout_graceful_shutdown=5,
        **uvicorn_ssl_kwargs(),
    )
