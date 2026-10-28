"""宗门灵藏玩法的稳定结果。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from game.core.sect_assets import SectAssetEntry, SectAssetTransfer


class LingcangFeatureError(RuntimeError):
    """当前玩家无法完成灵藏操作。"""


@dataclass(frozen=True)
class LingcangAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class LingcangPage:
    spirit_stones: int
    category: str
    page: int
    page_count: int
    total_entries: int
    entries: tuple[SectAssetEntry, ...]


@dataclass(frozen=True)
class LingcangCopy:
    text: Mapping[str, str]


@dataclass(frozen=True)
class LingcangEntry:
    """一次灵藏根命令的结果；分支与参数合规由玩法判定。"""

    kind: str
    page: LingcangPage | None = None
    quantity: int = 0
    transfer: SectAssetTransfer | None = None


__all__ = [
    "LingcangAction",
    "LingcangCopy",
    "LingcangEntry",
    "LingcangFeatureError",
    "LingcangPage",
    "SectAssetTransfer",
]
