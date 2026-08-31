"""公开地图命令回复构造。"""

from __future__ import annotations

from game.features.ditu import WorldMapOverview
from message import Action, DocumentMessage, M


def entry(overview: WorldMapOverview, url: str) -> DocumentMessage:
    builder = M.document().header(overview.name).section("全境舆图", icon="map")
    if overview.description:
        builder.line(overview.description)
    return (
        builder.row(
            ("范围", M.text(f"{overview.width} × {overview.height}", tone="emphasis")),
            ("区域", M.text(f"{overview.region_count}处", tone="emphasis")),
        )
        .row(
            ("地点", M.text(f"{overview.location_count}处", tone="emphasis")),
            ("道路", M.text(f"{overview.road_count}条", tone="emphasis")),
        )
        .line(M.link(f"打开{overview.name}地图", url))
        .action(Action("world_map.open", "打开地图", url, behavior="link"))
        .build()
    )


__all__ = ["entry"]
