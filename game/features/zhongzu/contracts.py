"""种族图鉴的公共结果。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class RaceEntry:
    """一个种族：编号是稳定标识，其余是登记表里的事实。

    `flavor` 是展示数据集里的族系风味句；`benefits` / `cost` 由 `天生规则[]` 经规则层 `卡面`
    合成——**不落库**：抄一份进数据就会漂（这正是本次重构要消灭的东西）。
    """

    number: str
    name: str
    lineage: str
    tiers: tuple[str, ...]
    lifespan: float
    benefits: tuple[str, ...]
    cost: str
    flavor: str


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


@dataclass(frozen=True)
class ZhongzuCopy:
    """种族展示文案（数据集的 展示/文本.json，不写死在代码里）。"""

    text: Mapping[str, Mapping[str, str]]


__all__ = ["RaceEntry", "RaceLineage", "RaceOverview", "ZhongzuCopy"]
