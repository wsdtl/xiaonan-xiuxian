"""世界地点与只读地图功能。"""

from .contracts import (
    JourneyMetrics,
    JourneyPassageSegment,
    JourneyPlan,
    JourneyQuery,
    LocationQuery,
    LocationView,
    MapCoordinateBand,
    MapLocation,
    MapRegion,
    MapRoad,
    MapTerrainZone,
    WorldMapView,
    WorldStatus,
)
from .service import WorldService

#: 世界实体的字段契约所在数据集、数据名与路径。
#: 地点道侣、炼器工匠、炼丹师、阵师都由世界组件提供，各自的领域核心据此校验。
WORLD_CONTRACT_DATASET = "世界定义"
WORLD_CONTRACT_NAME = "字段契约"
WORLD_CONTRACT_PATH = "世界/定义/字段契约.json"

__all__ = [
    "JourneyMetrics",
    "JourneyPassageSegment",
    "JourneyPlan",
    "JourneyQuery",
    "LocationQuery",
    "LocationView",
    "MapCoordinateBand",
    "MapLocation",
    "MapRegion",
    "MapRoad",
    "MapTerrainZone",
    "WORLD_CONTRACT_DATASET",
    "WORLD_CONTRACT_NAME",
    "WORLD_CONTRACT_PATH",
    "WorldMapView",
    "WorldService",
    "WorldStatus",
]
