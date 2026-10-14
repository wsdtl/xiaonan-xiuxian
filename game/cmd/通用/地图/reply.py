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


#: 一行放多少个字符（委托方 2026-10-15：一行 18 个字符，自行把握排列）。
_LINE_WIDTH = 18

#: 行内按钮之间的分隔：全角空格，与帮助卡一致。
_SEPARATOR = "　"


def _pack(labels: list[str], width: int = _LINE_WIDTH) -> list[list[str]]:
    """按**可见宽度**装箱：只数标签字数，按钮背后的长链接不占屏。"""

    rows: list[list[str]] = []
    row: list[str] = []
    used = 0
    for label in labels:
        need = len(label) + (len(_SEPARATOR) if row else 0)
        if row and used + need > width:
            rows.append(row)
            row, used = [], 0
            need = len(label)
        row.append(label)
        used += need
    if row:
        rows.append(row)
    return rows


def _button_rows(builder: object, labels: list[str], command: str) -> None:
    """把一串标签排成若干行，每行都是只填入的行内按钮。"""

    for row in _pack(labels):
        parts: list[object] = []
        for index, label in enumerate(row):
            if index:
                parts.append(_SEPARATOR)
            parts.append(M.command(label, command.format(label)))
        builder.line(*parts)


def _open_map(url: str) -> Action:
    return Action("world_map.open", "打开地图", url, behavior="link", style="primary")


def entry(overview: WorldMapOverview, url: str) -> DocumentMessage:
    """一页列全部大区域：每个区域一个行内按钮，点了把「地图 <州名>」填进输入框。"""

    builder = M.document().section("大区域", icon="location")
    if overview.description:
        builder.line(overview.description)
    _counts(builder, overview)
    _button_rows(builder, [region.name for region in overview.regions], "地图 {}")
    return builder.action(_open_map(url)).build()


def region(overview: WorldMapOverview, name: str, url: str) -> DocumentMessage:
    """一个州的细节：该州地点逐个行内可点（填入「行路 <地点>」）。"""

    for region in overview.regions:
        if region.name == name:
            builder = M.document().section(f"州 · {name}", icon="location")
            builder.line(f"地点 {len(region.locations)} 处")
            _button_rows(builder, list(region.locations), "去 {}")
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
    _button_rows(builder, [region.name for region in overview.regions], "地图 {}")
    return builder.action(_open_map(url)).build()


__all__ = ["entry", "region", "unknown_region"]
