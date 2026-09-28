"""托管玩法的业务入口与展示编排。"""

from __future__ import annotations

from game.core.hosting import HostingSession, HostingExecution, HostingError, HostingService

from game.core.data import JsonDataService

from .contracts import HostingCopy, HostingFeatureError, HostingResult
from .presentation import load_presentation


class HostingFeature:
    def __init__(self, data: JsonDataService, hosting: HostingService) -> None:
        self._data = data
        self._hosting = hosting
        self._copy: HostingCopy | None = None

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("托管玩法微服务已经初始化")
        if not self._hosting.status().initialized:
            raise RuntimeError("托管核心必须先于托管玩法启动")
        self._copy = load_presentation(self._data)

    def copy(self) -> HostingCopy:
        if self._copy is None:
            raise RuntimeError("托管玩法微服务尚未初始化")
        return self._copy

    async def start(
        self, user_id: str, request_id: str, activities: tuple[str, ...]
    ) -> HostingResult:
        try:
            session = await self._hosting.start(user_id, request_id, activities)
        except HostingError as exc:
            raise HostingFeatureError(exc.code) from exc
        return HostingResult("开启", session)

    async def current(self, user_id: str) -> HostingResult:
        try:
            session = await self._hosting.current(user_id)
            if session is not None:
                return HostingResult("查看", session)
            latest = await self._hosting.latest(user_id)
        except HostingError as exc:
            raise HostingFeatureError(exc.code) from exc
        return HostingResult("查看", latest, active=False)

    async def resume(self, user_id: str, request_id: str) -> HostingResult:
        try:
            session = await self._hosting.resume(user_id, request_id)
        except HostingError as exc:
            raise HostingFeatureError(exc.code) from exc
        return HostingResult("继续", session)

    async def cancel(self, user_id: str, request_id: str) -> HostingResult:
        try:
            session = await self._hosting.cancel(user_id, request_id)
        except HostingError as exc:
            raise HostingFeatureError(exc.code) from exc
        return HostingResult("取消", session, active=False)

    async def active_plans(self) -> tuple[HostingSession, ...]:
        return await self._hosting.active_plans()

    async def claim_execution(self, session_id: str) -> HostingExecution | None:
        return await self._hosting.claim_execution(session_id)

    async def verify_execution(self, execution: HostingExecution) -> bool:
        return await self._hosting.verify_execution(execution)

    async def complete_execution(
        self, execution: HostingExecution, *, success: bool, error: str = ""
    ) -> HostingSession | None:
        return await self._hosting.complete_execution(
            execution, success=success, error=error
        )


__all__ = ["HostingFeature"]
