"""宗门万珍殿玩法的稳定结果。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from game.core.sect_assets import SectAssetEntry


class WanzhenFeatureError(RuntimeError):
    """当前玩家无法完成万珍殿操作。"""


@dataclass(frozen=True)
class WanzhenAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class WanzhenPage:
    category: str
    page: int
    page_count: int
    total_entries: int
    entries: tuple[SectAssetEntry, ...]
    #: 条目上的先天灵宝编号 → 名字。渲染层只查这张表，不许自己去问服务（边界判据）。
    treasure_names: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class WanzhenOwnProduct:
    """玩家自己的一件成品：万珍殿只读台照着它拼「捐入」命令文本。"""

    category: str
    subcategory: str
    content_id: str
    entry_key: str
    grade_id: str
    quantity: int
    name: str
    treasure_id: str = ""
    treasure_name: str = ""
    treasure_effect: str = ""

@dataclass(frozen=True)
class WanzhenTransferResult:
    action: str
    entry: SectAssetEntry
    target_name: str = ""


@dataclass(frozen=True)
class WanzhenCopy:
    text: Mapping[str, str]


@dataclass(frozen=True)
class WanzhenEntry:
    """一次万珍殿根命令的结果；分支与参数合规由玩法判定。"""

    kind: str
    page: WanzhenPage | None = None
    transfer: WanzhenTransferResult | None = None


__all__ = [
    "WanzhenAction",
    "WanzhenCopy",
    "WanzhenEntry",
    "WanzhenFeatureError",
    "WanzhenOwnProduct",
    "WanzhenPage",
    "WanzhenTransferResult",
]
