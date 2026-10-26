"""辅助路由的公开只读 HTTP 接口；挂到框架现有 FastAPI。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from .service import AssistRouterService

router = APIRouter(prefix="/assist-router", tags=["assist-router"])


def bind(service: AssistRouterService) -> None:
    @router.get("/health")
    def health() -> dict:
        return service.stats()

    @router.get("/users/resolve")
    def resolve_user(
        bot_key: str = Query(...),
        openid: str = Query(...),
    ) -> dict:
        value = service.resolve_user(bot_key=bot_key, openid=openid)
        return {"found": value is not None, "route": value}

    @router.get("/groups/resolve")
    def resolve_group(
        bot_key: str = Query(...),
        group_openid: str = Query(...),
    ) -> dict:
        value = service.resolve_group(bot_key=bot_key, group_openid=group_openid)
        return {"found": value is not None, "route": value}


