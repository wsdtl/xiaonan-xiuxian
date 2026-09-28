"""把阵藏实例转换为待战阵法。"""

from __future__ import annotations

from game.core.formation import FormationArmResult, FormationError, FormationService

from collections.abc import Mapping
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService

from .contracts import FormationArmCopy, FormationArmFeatureError


class FormationArmFeature:
    """只编排布阵核心调用和第三人称展示。"""

    def __init__(self, data: JsonDataService, formation: FormationService) -> None:
        self._data = data
        self._formation = formation
        self._copy: FormationArmCopy | None = None

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("布阵玩法已经初始化")
        raw = self._data.dataset("阵法展示").get("文本")
        if not isinstance(raw, Mapping):
            raise JsonDataError("阵法展示缺少文本.json")
        text = MappingProxyType(
            {
                str(section): MappingProxyType(
                    {
                        str(key): str(value).strip()
                        for key, value in values.items()
                        if isinstance(value, str) and value.strip()
                    }
                )
                for section, values in raw.items()
                if isinstance(values, Mapping)
            }
        )
        if set(text.get("布阵", {})) != {"标题", "过程", "结果", "话语"}:
            raise JsonDataError("阵法布阵文本字段不完整")
        self._copy = FormationArmCopy(text)

    def copy(self) -> FormationArmCopy:
        if self._copy is None:
            raise RuntimeError("布阵玩法尚未初始化")
        return self._copy

    async def arm(self, user_id: str, request_id: str, identifier: str) -> FormationArmResult:
        try:
            return await self._formation.arm(user_id, request_id, identifier)
        except FormationError as exc:
            raise FormationArmFeatureError(str(exc)) from exc


__all__ = ["FormationArmFeature"]
