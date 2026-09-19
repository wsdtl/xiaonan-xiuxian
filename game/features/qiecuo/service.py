from __future__ import annotations

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
        if not isinstance(copy, Mapping):
            raise JsonDataError("玩法/切磋/展示/文本.json 必须是对象")
        self._copy = copy

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
