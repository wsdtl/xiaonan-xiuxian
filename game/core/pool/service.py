"""正式资源池抽取公共微服务。"""

from __future__ import annotations

import random
import secrets
from threading import RLock

from game.core.data import JsonDataService

from .contracts import (
    ALLOW_REPEATS,
    EXPAND_DEDUPLICATED,
    POOL_MODES,
    PoolEntry,
    PoolRequest,
    PoolResult,
    PoolStatus,
)
from .selection import inverse_weighted_sample

WEIGHTED_SECTIONS = frozenset({"敌人", "基础物品", "功法", "真意", "气机"})


class PoolService:
    """从 JSON 数据微服务展开候选，并执行统一逆权重抽取。"""

    def __init__(self, data: JsonDataService) -> None:
        self._data = data
        self._initialized = False
        self._candidate_lock = RLock()
        self._candidate_cache: dict[
            tuple[tuple[str, ...], str, bool, bool],
            tuple[PoolEntry, ...],
        ] = {}
        self._weights: dict[str, dict[str, int]] = {}

    def initialize(self) -> PoolStatus:
        if self._initialized:
            raise RuntimeError("资源池微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据微服务必须先于资源池微服务启动")
        for section in sorted(WEIGHTED_SECTIONS):
            self._weights[section] = {
                entity_id: _weight(entity_id, fields.get("权重"))
                for entity_id, fields in self._data.entity_fields(section, ("权重",))
            }
        self._initialized = True
        return self.status()

    def status(self) -> PoolStatus:
        return PoolStatus(
            initialized=self._initialized,
            modes=(ALLOW_REPEATS, EXPAND_DEDUPLICATED),
        )

    def draw(self, request: PoolRequest) -> PoolResult:
        if not self._initialized:
            raise RuntimeError("资源池微服务尚未初始化")
        selected_mode = str(request.mode or "").strip()
        if selected_mode not in POOL_MODES:
            raise ValueError(
                f"未知资源池抽取模式：{selected_mode or '<空>'}"
            )
        source_files = tuple(str(value).strip() for value in request.file_ids)
        if any(not value for value in source_files):
            raise ValueError("资源池文件名不能为空")
        if request.full_pool and source_files:
            raise ValueError("全池抽取不能同时指定资源池文件")
        if not request.full_pool and not source_files:
            raise ValueError("指定池抽取必须提供资源池文件")
        section_name = str(request.section or "").strip()
        if section_name not in WEIGHTED_SECTIONS:
            raise ValueError(
                f"该集合不使用权重抽取：{section_name or '<空>'}"
            )
        deduplicated = selected_mode == EXPAND_DEDUPLICATED
        candidates = self._candidates(
            source_files,
            section_name,
            deduplicated,
            request.full_pool,
        )
        seed_value = _seed(request.seed)
        entries = inverse_weighted_sample(
            random.Random(seed_value),
            candidates,
            tuple(entry.weight for entry in candidates),
            count=request.count,
            replace=not deduplicated,
        )
        return PoolResult(
            mode=selected_mode,
            seed=seed_value,
            section=section_name,
            source_files=source_files,
            full_pool=request.full_pool,
            candidate_count=len(candidates),
            entries=tuple(entries),
        )

    def draw_item_category(
        self, category: str, *, seed: int, count: int = 1
    ) -> tuple[str, ...]:
        """从全体物品中的一个基础材料类别按权重抽取编号。"""

        if not self._initialized:
            raise RuntimeError("资源池微服务尚未初始化")
        normalized = str(category or "").strip()
        candidates = tuple(
            entity_id
            for entity_id in self._weights["基础物品"]
            if self._data.entity_record("基础物品", entity_id).number_category
            == normalized
        )
        if not candidates:
            raise ValueError(f"物品类别没有可抽取候选：{normalized or '<空>'}")
        weights = tuple(self._weights["基础物品"][entity_id] for entity_id in candidates)
        selected = inverse_weighted_sample(
            random.Random(seed), candidates, weights, count=count, replace=True
        )
        return tuple(selected)

    def _candidates(
        self,
        source_files: tuple[str, ...],
        section: str,
        deduplicated: bool,
        full_pool: bool,
    ) -> tuple[PoolEntry, ...]:
        cache_key = (source_files, section, deduplicated, full_pool)
        with self._candidate_lock:
            cached = self._candidate_cache.get(cache_key)
            if cached is not None:
                return cached
            entity_ids = (
                self._data.all_members(section)
                if full_pool
                else self._data.pool_members(
                    source_files,
                    section,
                    deduplicate=deduplicated,
                )
            )
            candidates = tuple(
                PoolEntry(entity_id=entity_id, weight=self._weights[section][entity_id])
                for entity_id in entity_ids
            )
            self._candidate_cache[cache_key] = candidates
            return candidates


def _weight(entity_id: str, weight: object) -> int:
    if isinstance(weight, bool) or not isinstance(weight, int) or weight < 1:
        raise ValueError(f"资源池实体 {entity_id} 缺少正整数权重")
    return weight


def _seed(value: int | None) -> int:
    if value is None:
        return secrets.randbits(64)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("随机种子必须是整数")
    return value


__all__ = [
    "PoolService",
]
