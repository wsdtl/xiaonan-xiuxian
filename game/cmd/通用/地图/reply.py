"""公开地图命令回复构造。"""

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


def entry(overview: WorldMapOverview, url: str, index: int = 1) -> DocumentMessage:
    """一页一个区域：区域名 + 该区全部地点；引言与计数只在第 1 页。

    底部保留「打开地图」链接按钮；正文里不放同类的无边框超链接（重复，委托方 2026-10-14）。
    """

    total = max(1, len(overview.regions))
    index = min(max(1, index), total)
    region = overview.regions[index - 1]
    builder = M.document().header(overview.name).section(
        f"{region.category} · {region.name} · 第 {index} / {total} 页", icon="location"
    )
    if index == 1:
        if overview.description:
            builder.line(overview.description)
        _counts(builder, overview)
    builder.line("、".join(region.locations))
    actions: list[Action] = []
    if index > 1:
        actions.append(
            Action("world_map.previous", "上一页", f"地图 {index - 1}",
                   behavior="callback", style="secondary")
        )
    if index < total:
        actions.append(
            Action("world_map.next", "下一页", f"地图 {index + 1}",
                   behavior="callback", style="secondary")
        )
    actions.append(
        Action("world_map.open", "打开地图", url, behavior="link", style="primary")
    )
    return builder.actions(tuple(actions)).build()


def invalid_page(overview: WorldMapOverview, url: str) -> DocumentMessage:
    total = max(1, len(overview.regions))
    return (
        M.document()
        .header(overview.name)
        .section("没有这一页", icon="notice")
        .line(M.status("页码超出", tone="warning"), f" 共 {total} 页，发「地图 1」到「地图 {total}」。")
        .action(Action("world_map.open", "打开地图", url, behavior="link", style="primary"))
        .build()
    )


__all__ = ["entry", "invalid_page"]
