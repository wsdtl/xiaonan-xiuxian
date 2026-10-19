"""位置查看玩法微服务。"""

from .contracts import (
    StatusView,
    CompanionView,
    CurrentPositionView,
    NearbyCultivatorPage,
    NearbyCultivatorView,
    NearbyOverview,
    NearbyPageError,
    NearbyWorldLocation,
    NearbyWorldLocations,
    PositionAction,
    PositionCopy,
    PositionViewError,
)
from game.core.character.contracts import CharacterPublicProfile
from .service import PositionFeature

__all__ = [
    "CharacterPublicProfile",
    "CompanionView",
    "CurrentPositionView",
    "StatusView",
    "NearbyCultivatorPage",
    "NearbyCultivatorView",
    "NearbyOverview",
    "NearbyPageError",
    "NearbyWorldLocation",
    "NearbyWorldLocations",
    "PositionAction",
    "PositionCopy",
    "PositionFeature",
    "PositionViewError",
]
