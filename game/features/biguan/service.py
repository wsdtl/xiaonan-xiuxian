"""闭关参与者解析、结算与展示编排。"""

from __future__ import annotations

from datetime import datetime

from game.core.action_group import ActionGroupError, ActionGroupService
from game.core.asset import AssetService
from game.core.data import JsonDataService
from game.core.retreat import (
    RetreatError,
    RetreatProgress,
    RetreatService,
    RetreatSettlement,
    RetreatStartCommand,
    RetreatStarted,
)

from .contracts import RetreatAction, RetreatCopy, RetreatFeatureError
from .presentation import actions, load_presentation


class RetreatFeature:
    def __init__(
        self,
        data: JsonDataService,
        retreat: RetreatService,
        asset: AssetService,
        action_group: ActionGroupService,
    ) -> None:
        self._data = data
        self._retreat = retreat
        self._asset = asset
        self._action_group = action_group
        self._copy: RetreatCopy | None = None
        self._buttons = ()

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("闭关玩法已经初始化")
        if not self._retreat.status().initialized:
            raise RuntimeError("闭关核心必须先于闭关玩法启动")
        if not self._action_group.status().initialized:
            raise RuntimeError("行动编排核心必须先于闭关玩法启动")
        self._action_group.require_common_action("闭关", "闭关玩法")
        self._copy, self._buttons = load_presentation(self._data)

    def copy(self) -> RetreatCopy:
        if self._copy is None:
            raise RuntimeError("闭关玩法尚未初始化")
        return self._copy

    async def start(self, user_id: str, request_id: str) -> RetreatStarted:
        try:
            participants = await self._action_group.participants(user_id)
            return await self._retreat.start(
                RetreatStartCommand(user_id, request_id, participants)
            )
        except ActionGroupError as exc:
            message = (
                "当前正在跟随领队，只有领队可以发起闭关（可看闭关进度，等领队统一出关）"
                if exc.code == "member_cannot_start"
                else "同行状态刚刚发生变化"
            )
            raise RetreatFeatureError(message) from exc
        except RetreatError as exc:
            raise RetreatFeatureError(str(exc)) from exc

    async def progress(
        self, user_id: str, *, now: datetime | None = None
    ) -> RetreatProgress:
        try:
            return await self._retreat.progress(user_id, now=now)
        except RetreatError as exc:
            raise RetreatFeatureError(str(exc)) from exc

    async def settle(
        self, user_id: str, request_id: str, *, now: datetime | None = None
    ) -> RetreatSettlement:
        try:
            return await self._retreat.settle(user_id, request_id, now=now)
        except RetreatError as exc:
            raise RetreatFeatureError(str(exc)) from exc

    def started_actions(self) -> tuple[RetreatAction, ...]:
        return actions(self._buttons, "开始", {"可以出关"})

    def progress_actions(self, can_end: bool) -> tuple[RetreatAction, ...]:
        return actions(self._buttons, "进度", {"可以出关"} if can_end else set())

    def settlement_actions(
        self, page: int, total_pages: int
    ) -> tuple[RetreatAction, ...]:
        return paged_settlement_actions(actions, self._buttons, page=page, total_pages=total_pages)

    def cultivation_label(self, content_id: str, grade_id: str) -> str:
        name = str(self._data.entity("功法", content_id).get("名称") or content_id)
        return f"{self._asset.grade(grade_id).name}{name}"


__all__ = ["RetreatFeature"]
