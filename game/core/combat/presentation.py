"""战报展示入口。

页面只有一份数据：整场动画契约。文本模式也从同一份 JSON 组装，
不再维护首屏/片段/事件/参战者/转场五套投影。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .animation import build_animation_view
from .catalog import BattleReportCatalog

VIEW_PARTS = ("animation",)


def build_battle_report_view(
    report: Mapping[str, Any],
    catalog: BattleReportCatalog,
    *,
    only: str | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    if only not in (None, "animation"):
        raise ValueError(f"战报视图不认识这一份：{only}")
    return {}, {"animation": build_animation_view(report, catalog)}


__all__ = ["VIEW_PARTS", "build_battle_report_view"]
