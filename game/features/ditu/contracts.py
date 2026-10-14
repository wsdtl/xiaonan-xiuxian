"""公开地图展示玩法的公共结果。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorldMapRegion:
    """一块区域，以及它地界上的全部地点名（按区域名分组，顺序与世界数据一致）。"""

    name: str
    category: str
    locations: tuple[str, ...]


@dataclass(frozen=True)
class WorldMapOverview:
    name: str
    description: str
    width: int
    height: int
    region_count: int
    location_count: int
    road_count: int
    regions: tuple[WorldMapRegion, ...] = ()


__all__ = ["WorldMapOverview", "WorldMapRegion"]
