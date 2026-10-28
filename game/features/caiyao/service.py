"""采药参与者解析与展示编排。"""

from __future__ import annotations

from datetime import datetime

from game.core.action_group import ActionGroupError, ActionGroupService
from game.core.asset import AssetService
from game.core.data import JsonDataService
from game.core.gathering import (
    GatheringError,
    GatheringProgress,
    GatheringService,
    GatheringSettlement,
    GatheringStartCommand,
    GatheringStarted,
)

from .contracts import (
    HerbGatheringAction,
    HerbGatheringCopy,
    HerbGatheringEntry,
    HerbGatheringFeatureError,
)
from game.features.presentation import paged_settlement_actions
from .presentation import actions, load_presentation

KIND = "采药"


class HerbGatheringFeature:
    def __init__(
        self,
        data: JsonDataService,
        gathering: GatheringService,
        asset: AssetService,
        action_group: ActionGroupService,
    ) -> None:
        self._data = data
        self._gathering = gathering
        self._asset = asset
        self._action_group = action_group
        self._copy: HerbGatheringCopy | None = None
        self._buttons: tuple[dict[str, str], ...] | tuple = ()

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("采药玩法已经初始化")
        self._gathering.mode_status(KIND)
        if not self._action_group.status().initialized:
            raise RuntimeError("行动编排核心必须先于采药玩法启动")
        self._action_group.require_common_action("采药", "采药玩法")
        self._copy, self._buttons = load_presentation(self._data)

    def copy(self) -> HerbGatheringCopy:
        if self._copy is None:
            raise RuntimeError("采药玩法尚未初始化")
        return self._copy

    async def start(self, user_id: str, request_id: str) -> GatheringStarted:
        try:
            participants = await self._action_group.participants(user_id)
            return await self._gathering.start(
                GatheringStartCommand(KIND, user_id, request_id, participants)
            )
        except ActionGroupError as exc:
            message = (
                "当前正在跟随领队，只有领队可以发起采药（可看采药进度，等领队统一结束）"
                if exc.code == "member_cannot_start"
                else "同行状态刚刚发生变化"
            )
            raise HerbGatheringFeatureError(message) from exc
        except (GatheringError, ValueError) as exc:
            raise HerbGatheringFeatureError(str(exc)) from exc

    async def enter(
        self, user_id: str, request_id: str, raw_message: str
    ) -> HerbGatheringEntry:
        """解析采药根命令与紧凑子命令；分支合规只由本玩法判定。"""

        text = str(raw_message or "").strip()
        if text.startswith("采药"):
            text = text[2:].strip()
        action, _, args = text.partition(" ")
        action = action.strip()
        args = args.strip()
        if not action:
            return await self._enter_default(user_id, request_id)
        if action == "开始":
            if args:
                raise self._invalid_command()
            return HerbGatheringEntry(
                "started", started=await self.start(user_id, request_id)
            )
        if action == "进度":
            if args:
                raise self._invalid_command()
            return HerbGatheringEntry("progress", progress=await self.progress(user_id))
        if action in {"结束", "结果"}:
            page = self._page_number(args)
            result = await self.settle(user_id, request_id)
            total_pages = 1 + len(result.users)
            if page < 1 or page > total_pages:
                raise HerbGatheringFeatureError(f"页码必须在1至{total_pages}之间")
            return HerbGatheringEntry(
                "settlement",
                settlement=result,
                page=page,
                total_pages=total_pages,
            )
        raise self._invalid_command()

    async def _enter_default(
        self, user_id: str, request_id: str
    ) -> HerbGatheringEntry:
        try:
            result = await self.progress(user_id)
        except HerbGatheringFeatureError:
            return HerbGatheringEntry(
                "started", started=await self.start(user_id, request_id)
            )
        if result.settled and not result.can_end:
            return HerbGatheringEntry(
                "started", started=await self.start(user_id, request_id)
            )
        return HerbGatheringEntry("progress", progress=result)

    def _page_number(self, args: str) -> int:
        if not args:
            return 1
        try:
            page = int(args)
        except ValueError as exc:
            raise self._invalid_command() from exc
        if page < 1:
            raise self._invalid_command()
        return page

    def _invalid_command(self) -> HerbGatheringFeatureError:
        text = self.copy().text
        return HerbGatheringFeatureError(
            str(text.get("错误", {}).get("写法", "写法错误"))
        )

    async def progress(
        self, user_id: str, *, now: datetime | None = None
    ) -> GatheringProgress:
        try:
            return await self._gathering.progress(KIND, user_id, now=now)
        except (GatheringError, ValueError) as exc:
            raise HerbGatheringFeatureError(str(exc)) from exc

    async def settle(
        self, user_id: str, request_id: str, *, now: datetime | None = None
    ) -> GatheringSettlement:
        try:
            return await self._gathering.settle(KIND, user_id, request_id, now=now)
        except (GatheringError, ValueError) as exc:
            raise HerbGatheringFeatureError(str(exc)) from exc


    def format_actions(self) -> tuple[object, ...]:
        """格式与提示类回执的动作：只给「查看帮助」——完整用法在帮助组件里。"""

        return actions(self._buttons, "格式", set())
    def started_actions(self) -> tuple[HerbGatheringAction, ...]:
        return actions(self._buttons, "开始", {"可以结束"})

    def progress_actions(self, can_end: bool) -> tuple[HerbGatheringAction, ...]:
        return actions(self._buttons, "进度", {"可以结束"} if can_end else set())

    def settlement_actions(
        self, page: int, total_pages: int
    ) -> tuple[HerbGatheringAction, ...]:
        return paged_settlement_actions(actions, self._buttons, page=page, total_pages=total_pages)

    def item_name(self, item_id: str) -> str:
        """只取名字（不带品级），给「查看」这类联动当参数用。"""
        item = self._data.entity("基础物品", item_id)
        return str(item.get("名称") or item_id)

    def item_label(self, item_id: str, grade_id: str) -> str:
        item = self._data.entity("基础物品", item_id)
        return f"{self._asset.grade(grade_id).name}{item.get('名称') or item_id}"


__all__ = ["HerbGatheringFeature"]
