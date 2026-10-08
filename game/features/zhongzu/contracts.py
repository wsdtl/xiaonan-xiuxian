"""种族图鉴的公共结果。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RaceEntry:
    """一个种族：编号是它的稳定标识，其余是登记表里的展示事实。"""

    number: str
    name: str
    lineage: str
    tiers: tuple[str, ...]
    lifespan: float
    summary: str


@dataclass(frozen=True)
class RaceLineage:
    """一个族系下的全部种族，按编号排序。"""

    name: str
    races: tuple[RaceEntry, ...]


@dataclass(frozen=True)
class RaceOverview:
    """种族图鉴首页：族系分组 + 总数 + 档次次序。"""

    total: int
    lineages: tuple[RaceLineage, ...]
    tiers: tuple[str, ...]


__all__ = ["RaceEntry", "RaceLineage", "RaceOverview"]
