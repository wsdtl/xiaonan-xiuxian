"""公开地图命令回复构造。

单页可点（委托方 2026-10-15）：`地图` 一页列全部大区域，每个区域做成**行内无边框按钮**
（只填入，点一下变成 `地图 <州名>`）；`地图 <州名>` 列该州地点，地点同样行内可点
（填入 `行路 <地点>`）。各层底部保留「打开地图」网页按钮。
"""

from __future__ import annotations

from game.features.ditu import WorldMapOverview
from message import Action, DocumentMessage, M


def _counts(builder: object, overview: WorldMapOverview) -> None:
    builder.row(
        ("范围", M.text(f"{overview.width} × {overview.height}", tone="emphasis")),
        ("区域", M.text(f"{overview.region_count}处", tone="emphasis")),
    ).row(
        ("地点", M.text(f"{overview.location_count}处", tone="emphasis")),
        ("道路", M.text(f"{overview.road_count}条", tone="emphasis")),
    )


def _open_map(url: str) -> Action:
    return Action("world_map.open", "打开地图", url, behavior="link", style="primary")


def entry(overview: WorldMapOverview, url: str) -> DocumentMessage:
    """一页列全部大区域：每个区域一个行内按钮，点了把「地图 <州名>」填进输入框。"""

    builder = M.document().section("大区域", icon="location")
    if overview.description:
        builder.line(overview.description)
    _counts(builder, overview)
    for region in overview.regions:
        builder.line(M.command(region.name, f"地图 {region.name}"))
    return builder.action(_open_map(url)).build()


def region(overview: WorldMapOverview, name: str, url: str) -> DocumentMessage:
    """一个州的细节：该州地点逐个行内可点（填入「行路 <地点>」）。"""

    for region in overview.regions:
        if region.name == name:
            builder = M.document().section(f"州 · {name}", icon="location")
            builder.line(f"地点 {len(region.locations)} 处")
            for location in region.locations:
                builder.line(M.command(location, f"去 {location}"))
            return (
                builder.action(
                    Action(
                        "world_map.back",
                        "全部区域",
                        "地图",
                        behavior="callback",
                        style="secondary",
                    )
                )
                .action(_open_map(url))
                .build()
            )
    return unknown_region(overview, name, url)


def unknown_region(overview: WorldMapOverview, name: str, url: str) -> DocumentMessage:
    """州名不认识时的提示卡：把现有大区域列出来，照样可点。"""

    builder = M.document().section("没有这个州", icon="notice")
    builder.line(M.status("未找到", tone="warning"), f" 没有登记过这个州：{name}")
    builder.line("现有大区域：")
    for region in overview.regions:
        builder.line(M.command(region.name, f"地图 {region.name}"))
    return builder.action(_open_map(url)).build()


__all__ = ["entry", "region", "unknown_region"]
