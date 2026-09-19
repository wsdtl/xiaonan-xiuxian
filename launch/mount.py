"""FastAPI 资源和通信驱动器挂载。

静态资源与驱动器 HTTP 入口都在此统一接入应用。内部驱动器可以参与生命周期，
但没有 HTTP mount，例如本地驱动器不会暴露调试接口。
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

if TYPE_CHECKING:
    from os import PathLike

    from fastapi import FastAPI

from .adapter import BaseAdapter, enabled_adapter_specs
from .log import C, logger
from .paths import STATIC_DIR


class NoCacheStaticFiles(StaticFiles):
    """静态资源一律「每次回来问一遍」，由 ETag 决定是 304 还是新内容。

    以前不给缓存头，浏览器按自己的启发式规则缓存，于是 `index.html` 里出现了
    手工维护的 `?v=1`、`?v=2`、`?v=20`、`?v=47`——**同一个页面的 CSS 与 JS 用着不同的
    号，还得连 `import "./ui.js?v=20"` 一起改**，漏一处就是老文件配新文件。
    页面本身是 `no-store`，资源再走启发式缓存没有意义：这里统一要求重新验证，
    内容没变时仍然只回 304，版本号就不必再由人记。
    """

    def file_response(
        self,
        full_path: PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = "no-cache"
        return response


def FastAPIMount(app: FastAPI) -> None:
    """挂载项目静态资源；重复调用时保持幂等。"""

    STATIC_DIR.mkdir(parents=True, exist_ok=True)

    if any(getattr(route, "path", "") == "/static" for route in app.routes):
        return

    app.mount("/static", NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")


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
