"""FastAPI 资源和通信驱动器挂载。

静态资源与驱动器 HTTP 入口都在此统一接入应用。内部驱动器可以参与生命周期，
但没有 HTTP mount，例如本地驱动器不会暴露调试接口。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.staticfiles import StaticFiles

if TYPE_CHECKING:
    from fastapi import FastAPI

from .adapter import BaseAdapter, enabled_adapter_specs
from .log import C, logger
from .paths import STATIC_DIR


def FastAPIMount(app: FastAPI) -> None:
    """挂载项目静态资源；重复调用时保持幂等。"""

    STATIC_DIR.mkdir(parents=True, exist_ok=True)

    if any(getattr(route, "path", "") == "/static" for route in app.routes):
        return

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def AdapterMount(app: FastAPI) -> list[type[BaseAdapter]]:
    """挂载适配器的 HTTP 入口，并返回需要启动/关闭的处理器。

    没有 HTTP 入口的 Local 驱动仍会参与生命周期，只是不会向 FastAPI 暴露
    路由。
    """

    adapters: list[type[BaseAdapter]] = []

    for spec in enabled_adapter_specs():
        mount = spec.http_mount
        if mount is not None and not _has_path(app, mount.path):
            app.include_router(mount.router)
            logger.opt(colors=True).success(
                f"{C.ok('已挂载适配器')} {C.kv('name', spec.name)} {C.kv('path', mount.path)}"
            )

        adapters.append(spec.handler)

    return adapters


def _has_path(app: FastAPI, path: str) -> bool:
    """判断应用是否已经挂载指定路径，避免重复 include。"""

    return any(getattr(route, "path", "") == path for route in app.routes)
