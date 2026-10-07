"""命令与 HTTP 展示入口聚合。"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from pkgutil import walk_packages

from fastapi import APIRouter



def _load_component_routers() -> APIRouter:
    router = APIRouter()
    package_path = [str(Path(__file__).parent)]
    components = sorted(
        walk_packages(package_path, prefix=f"{__name__}."),
        key=lambda item: item.name,
    )
    for component in components:
        if not component.ispkg:
            continue
        module = import_module(component.name)
        component_router = getattr(module, "router", None)
        if component_router is None:
            continue
        if not isinstance(component_router, APIRouter):
            raise TypeError(f"命令组件 router 必须是 APIRouter：{module.__name__}")
        router.include_router(component_router)
    return router


router = _load_component_routers()


__all__ = ["router"]
