from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DuelAction:
    """切磋回执上的动作，字段名与 CommandAction 契约一致。"""

    action_id: str
    label: str
    command: str
    behavior: str
    style: str

from collections.abc import Mapping

from game.core.character import CharacterService
from game.core.data import JsonDataError, JsonDataService
from game.core.duel import (
    DuelChallenge,
    DuelError,
    DuelResult,
    DuelService,
    DuelStartCommand,
)


class DuelFeature:
    def __init__(
        self, data: JsonDataService, duel: DuelService, character: CharacterService
    ) -> None:
        self._data = data
        self._duel = duel
        self._character = character
        self._copy: Mapping[str, object] | None = None

    def initialize(self) -> None:
        copy = self._data.dataset("切磋展示").get("文本")
        self._format_actions = tuple(
            DuelAction(
                str(row["编号"]), str(row["名称"]), str(row["命令"]),
                str(row["行为"]), str(row["样式"]),
            )
            for row in (self._data.dataset("切磋按钮").get("按钮") or ())
            if isinstance(row, Mapping)
        )
        if not isinstance(copy, Mapping):
            raise JsonDataError("玩法/切磋/展示/文本.json 必须是对象")
        self._copy = copy

    def format_actions(self) -> tuple[DuelAction, ...]:
        """格式与提示类回执的动作：只给「查看帮助」。"""

        return self._format_actions


    def text(self, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
        if self._copy is None:
            raise RuntimeError("切磋玩法尚未初始化")
        value = self._copy.get(section, {})
        result = value.get(key) if isinstance(value, Mapping) else None
        if not isinstance(result, str):
            raise TypeError(f"切磋展示缺少文本：{section}.{key}")
        return result.format_map(values or {})

    async def resolve_target(self, user_id: str, query: str) -> str:
        return await self._duel.resolve_target(user_id, query)

    async def target_name(self, target_user_id: str) -> str:
        profiles = await self._character.public_profiles((target_user_id,))
        if not profiles:
            raise DuelError("切磋目标的人物信息不存在")
        return profiles[0].name

    def winner_label(self, winner: str, challenger_name: str, target_name: str) -> str:
        if winner == "left":
            return f"{challenger_name}一方"
        if winner == "right":
            return f"{target_name}一方"
        return self.text("结果", "平局")

    async def start(self, command: DuelStartCommand) -> DuelChallenge:
        return await self._duel.start(command)

    async def accept(self, user_id: str, request_id: str) -> DuelResult:
        return await self._duel.accept(user_id, request_id)

    async def reject(self, user_id: str, request_id: str) -> None:
        await self._duel.reject(user_id, request_id)

    async def withdraw(self, user_id: str, request_id: str) -> DuelChallenge:
        return await self._duel.withdraw(user_id, request_id)
