"""普通探险的业务入口与展示编排。"""

from __future__ import annotations

from datetime import datetime

from game.core.action_group import ActionGroupError, ActionGroupService
from game.core.asset import AssetService
from game.core.data import JsonDataService
from game.core.exploration import (
    ExplorationError,
    ExplorationProgress,
    ExplorationService,
    ExplorationSettlement,
    ExplorationStartCommand,
    ExplorationStarted,
)
from game.core.item_catalog import ItemCatalogService

from .contracts import ExplorationAction, ExplorationCopy, ExplorationFeatureError
from .presentation import actions, load_presentation


class ExplorationFeature:
    def __init__(
        self,
        data: JsonDataService,
        exploration: ExplorationService,
        items: ItemCatalogService,
        asset: AssetService,
        action_group: ActionGroupService,
    ) -> None:
        self._data = data
        self._exploration = exploration
        self._items = items
        self._asset = asset
        self._action_group = action_group
        self._copy: ExplorationCopy | None = None
        self._buttons = ()

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("探险玩法已经初始化")
        if not self._exploration.status().initialized:
            raise RuntimeError("探险核心必须先于玩法微服务启动")
        if not self._action_group.status().initialized:
            raise RuntimeError("行动编排核心必须先于探险玩法启动")
        self._action_group.require_common_action("探险", "探险玩法")
        self._copy, self._buttons = load_presentation(self._data)

    def copy(self) -> ExplorationCopy:
        if self._copy is None:
            raise RuntimeError("探险玩法尚未初始化")
        return self._copy

    async def start(self, user_id: str, request_id: str) -> ExplorationStarted:
        try:
            participants = await self._action_group.participants(user_id)
            return await self._exploration.start(
                ExplorationStartCommand(user_id, request_id, participants)
            )
        except ActionGroupError as exc:
            message = (
                "当前正在跟随领队，只有领队可以发起探险（可看探险进度，等领队统一结算）"
                if exc.code == "member_cannot_start"
                else "同行状态刚刚发生变化"
            )
            raise ExplorationFeatureError(message) from exc
        except ExplorationError as exc:
            raise ExplorationFeatureError(str(exc)) from exc

    async def progress(
        self, user_id: str, *, now: datetime | None = None
    ) -> ExplorationProgress:
        try:
            return await self._exploration.progress(user_id, now=now)
        except ExplorationError as exc:
            raise ExplorationFeatureError(str(exc)) from exc

    async def settle(
        self, user_id: str, request_id: str, *, now: datetime | None = None
    ) -> ExplorationSettlement:
        try:
            return await self._exploration.settle(user_id, request_id, now=now)
        except ExplorationError as exc:
            raise ExplorationFeatureError(str(exc)) from exc

    def start_actions(self) -> tuple[ExplorationAction, ...]:
        return actions(self._buttons, "开始", set())

    def progress_actions(
        self, ended: bool, can_settle: bool
    ) -> tuple[ExplorationAction, ...]:
        return actions(
            self._buttons,
            "进度",
            {"可以结算"} if ended and can_settle else set(),
        )

    def settlement_actions(
        self, page: int, total_pages: int
    ) -> tuple[ExplorationAction, ...]:
        conditions = set()
        if page > 1:
            conditions.add("存在上一页")
        if page < total_pages:
            conditions.add("存在下一页")
        return actions(
            self._buttons,
            "总结",
            conditions,
            {"上一页": page - 1, "下一页": page + 1},
        )

    def item_label(self, item_id: str, grade_id: str) -> str:
        return f"{self._asset.grade(grade_id).name}{self._items.get(item_id).name}"


__all__ = ["ExplorationFeature"]
