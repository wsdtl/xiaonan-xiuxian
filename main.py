"""晓楠修仙 HTTP 服务入口。"""

from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from loguru import logger

from launch import (
    LOGGING_CONFIG,
    FastAPIAllowed,
    FastAPIIncludeRouter,
    config,
    lifespan,
)


def ensure_certs_dir() -> Path:
    """`certs/` 不进包，新部署时它可能不存在：先把位置建出来，方便往里放证书。

    与 `log/`、`.runtime/`、`database/` 同理——运行期目录由程序按需创建，替包部署只带代码与数据。
    """

    directory = config.base_dir / "certs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def uvicorn_ssl_kwargs() -> dict[str, str]:
    """按 `.env` 与证书**实际在不在**决定 HTTP 还是 HTTPS。

    - 没配 `SERVER_SSL_CERTFILE` / `SERVER_SSL_KEYFILE` → HTTP；
    - 配了但文件不在（新部署还没把证书放进去）→ **退回 HTTP 并告警**，
      不让「证书没放」变成「服务起不来」；
    - 两个文件都在 → HTTPS。
    """

    certfile = config.server.ssl_certfile
    keyfile = config.server.ssl_keyfile
    if not certfile or not keyfile:
        return {}
    if not Path(certfile).is_file() or not Path(keyfile).is_file():
        logger.warning(
            "证书文件不存在（{} / {}），本次以 HTTP 启动；把证书放进 {} 并在 .env 里设好 "
            "SERVER_SSL_CERTFILE 与 SERVER_SSL_KEYFILE 即可改用 HTTPS",
            certfile,
            keyfile,
            config.base_dir / "certs",
        )
        return {}
    return {
        "ssl_certfile": str(certfile),
        "ssl_keyfile": str(keyfile),
    }


def create_app() -> FastAPI:
    """加载命令模块，挂载消息驱动器并创建应用。"""

    ensure_certs_dir()
    app = FastAPI(
        title=config.project.name,
        debug=config.project.debug,
        lifespan=lifespan,
    )
    FastAPIAllowed(app)
    FastAPIIncludeRouter(app)
    return app


# 不要在 Windows 上改事件循环策略：`asyncio.set_event_loop_policy` 与
# `WindowsSelectorEventLoopPolicy` 都已弃用，而全库没有任何地方用 Selector 循环
# 独有的 `add_reader`——HTTP/WebSocket 与 APScheduler 在默认的 Proactor 上都跑得动。
if __name__ == "__main__":
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
