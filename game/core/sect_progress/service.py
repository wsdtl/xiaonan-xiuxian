"""按当前宗门成员贡献计算宗门等级与资源增益。"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

from game.core.character import CharacterService
from game.core.data import (
    JsonDataError,
    JsonDataService,
    mapping as _mapping,
    nonempty_text,
    positive_int as _positive_int,
)
from game.core.sect import SectService

from .contracts import SectProgressError, SectProgressSnapshot, SectProgressStatus


class SectProgressService:
    """不保存宗门等级；每次根据当前成员的个人贡献计算。"""

    def __init__(
        self, data: JsonDataService, sect: SectService, character: CharacterService
    ) -> None:
        self._data = data
        self._sect = sect
        self._character = character
        self._initialized = False
        self._thresholds: tuple[int, ...] = ()
        self._production: tuple[float, ...] = ()
        self._gathering: tuple[float, ...] = ()
        self._facility_cost: tuple[float, ...] = ()

    def initialize(self) -> SectProgressStatus:
        if self._initialized:
            raise RuntimeError("宗门贡献等级核心已经初始化")
        raw = _mapping(self._data.dataset("宗门规则").get("宗门"), "宗门.json")
        level = _mapping(raw.get("等级"), "宗门.等级")
        maximum = _positive_int(level.get("最高等级"), "宗门.等级.最高等级")
        thresholds = _positive_or_zero_ints(level.get("阈值"), "宗门.等级.阈值")
        if len(thresholds) != maximum or thresholds[0] != 0:
            raise JsonDataError("宗门等级阈值必须从0开始且与最高等级一致")
        if any(current <= previous for previous, current in pairwise(thresholds)):
            raise JsonDataError("宗门等级阈值必须递增")
        gains = _mapping(level.get("增益"), "宗门.等级.增益")
        self._thresholds = thresholds
        self._production = _multipliers(gains.get("生产数量倍率"), maximum, "生产数量倍率")
        self._gathering = _multipliers(gains.get("采集数量倍率"), maximum, "采集数量倍率")
        self._facility_cost = _multipliers(gains.get("炼制灵石消耗倍率"), maximum, "炼制灵石消耗倍率")
        self._initialized = True
        return self.status()

    def status(self) -> SectProgressStatus:
        return SectProgressStatus(self._initialized, len(self._thresholds))

    async def snapshot(self, sect_id: str) -> SectProgressSnapshot:
        self._require()
        normalized = _text(sect_id, "sect_id")
        members = await self._sect.members(normalized)
        total = sum(
            contribution
            for _, contribution in await self._character.contributions(
                tuple(member.user_id for member in members)
            )
        )
        level_index = 0
        for index, threshold in enumerate(self._thresholds):
            if total >= threshold:
                level_index = index
            else:
                break
        next_threshold = (
            self._thresholds[level_index + 1]
            if level_index + 1 < len(self._thresholds)
            else None
        )
        return SectProgressSnapshot(
            normalized,
            level_index + 1,
            len(self._thresholds),
            total,
            next_threshold,
            self._production[level_index],
            self._gathering[level_index],
            self._facility_cost[level_index],
        )

    def _require(self) -> None:
        if not self._initialized:
            raise RuntimeError("宗门贡献等级核心尚未初始化")


def _positive_or_zero_ints(value: object, label: str) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError(f"{label}必须是整数数组")
    result = tuple(value)
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in result):
        raise JsonDataError(f"{label}必须是非负整数数组")
    return result


def _multipliers(value: object, maximum: int, label: str) -> tuple[float, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError(f"宗门.等级.增益.{label}必须是数字数组")
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
        raise JsonDataError(f"宗门.等级.增益.{label}必须是数字数组")
    result = tuple(float(item) for item in value)
    if len(result) != maximum or any(
        not math.isfinite(item) or item <= 0 for item in result
    ):
        raise JsonDataError(f"宗门.等级.增益.{label}长度或数值无效")
    if tuple(sorted(result)) != result and label != "炼制灵石消耗倍率":
        raise JsonDataError(f"宗门.等级.增益.{label}必须递增")
    if label == "炼制灵石消耗倍率" and tuple(sorted(result, reverse=True)) != result:
        raise JsonDataError(f"宗门.等级.增益.{label}必须递减")
    return result


def _text(value: object, label: str) -> str:
    return nonempty_text(value, label, error=SectProgressError)


__all__ = ["SectProgressService"]
