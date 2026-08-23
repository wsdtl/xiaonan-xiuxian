from __future__ import annotations

from collections.abc import Mapping

from game.core.data import JsonDataError, JsonDataService
from game.core.duel import DuelChallenge, DuelResult, DuelService, DuelStartCommand


class DuelFeature:
    def __init__(self, data: JsonDataService, duel: DuelService) -> None:
        self._data = data
        self._duel = duel
        self._copy: Mapping[str, object] | None = None

    def initialize(self) -> None:
        copy = self._data.dataset("切磋展示").get("文本")
        if not isinstance(copy, Mapping):
            raise JsonDataError("展示/切磋/文本.json 必须是对象")
        self._copy = copy

    def text(self, section: str, key: str, **values: object) -> str:
        if self._copy is None:
            raise RuntimeError("切磋玩法尚未初始化")
        value = self._copy.get(section, {})
        result = value.get(key) if isinstance(value, Mapping) else None
        if not isinstance(result, str):
            raise TypeError(f"切磋展示缺少文本：{section}.{key}")
        return result.format_map(values)

    async def resolve_target(self, user_id: str, query: str) -> str:
        return await self._duel.resolve_target(user_id, query)

    async def start(self, command: DuelStartCommand) -> DuelChallenge:
        return await self._duel.start(command)

    async def accept(self, user_id: str, request_id: str) -> DuelResult:
        return await self._duel.accept(user_id, request_id)

    async def reject(self, user_id: str, request_id: str) -> None:
        await self._duel.reject(user_id, request_id)
