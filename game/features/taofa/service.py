"""讨伐玩法入口与展示数据解释。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType

from game.core.action_group import ActionGroupError, ActionGroupService
from game.core.data import JsonDataError, JsonDataService
from game.core.raid import (
    RaidError,
    RaidProgress,
    RaidService,
    RaidSettlement,
    RaidStartCommand,
    RaidStarted,
)

from .contracts import RaidFeatureError


class RaidFeature:
    def __init__(
        self, data: JsonDataService, raid: RaidService, groups: ActionGroupService
    ) -> None:
        self._data, self._raid, self._groups = data, raid, groups
        self._text: Mapping[str, Mapping[str, str]] = MappingProxyType({})

    def initialize(self) -> None:
        raw = self._data.dataset("讨伐展示")
        if not isinstance(raw, Mapping):
            raise JsonDataError("讨伐展示缺少文本.json")
        text = raw.get("文本")
        if not isinstance(text, Mapping):
            raise JsonDataError("讨伐展示缺少文本.json")
        self._text = MappingProxyType(
            {
                str(section): MappingProxyType(
                    {str(k): str(v) for k, v in value.items()}
                )
                for section, value in text.items()
                if isinstance(value, Mapping)
            }
        )

    def text(self, section: str, key: str, **values: object) -> str:
        return self._text[section][key].format_map(values)

    async def start(self, user_id: str, request_id: str) -> RaidStarted:
        try:
            participants = await self._groups.participants(user_id)
            return await self._raid.start(
                RaidStartCommand(user_id, request_id, participants)
            )
        except ActionGroupError as exc:
            message = (
                "当前正在跟随领队，只有领队可以发起讨伐"
                if exc.code == "member_cannot_start"
                else "同行状态刚刚发生变化"
            )
            raise RaidFeatureError(message) from exc
        except RaidError as exc:
            raise RaidFeatureError(str(exc)) from exc

    async def progress(
        self, user_id: str, *, now: datetime | None = None
    ) -> RaidProgress:
        try:
            return await self._raid.progress(user_id, now=now)
        except RaidError as exc:
            raise RaidFeatureError(str(exc)) from exc

    async def settle(
        self, user_id: str, request_id: str, *, now: datetime | None = None
    ) -> RaidSettlement:
        try:
            return await self._raid.settle(user_id, request_id, now=now)
        except RaidError as exc:
            raise RaidFeatureError(str(exc)) from exc

    def result_label(self, winner: str) -> str:
        key = {"left": "胜利", "right": "失败", "平局": "平局"}.get(winner, "平局")
        return self.text("结算", key)

    def reward_note(self, winner: str) -> str:
        key = {"left": "胜利奖励", "right": "失败奖励", "平局": "平局奖励"}.get(
            winner, "平局奖励"
        )
        return self.text("结算", key)
