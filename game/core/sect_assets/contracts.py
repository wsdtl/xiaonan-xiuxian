"""宗门灵藏与万珍殿的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.database import SharedEntityMutation
from game.core.innate_treasure import InnateTreasureActivation


class SectAssetError(RuntimeError):
    """宗门公共资产无法完成当前操作。"""


class SectAssetConflictError(SectAssetError):
    """宗门或相关资产在事务期间已经变化。"""


@dataclass(frozen=True)
class SectAssetStatus:
    initialized: bool
    material_categories: tuple[str, ...]
    product_categories: tuple[str, ...]


@dataclass(frozen=True)
class SectAssetEntry:
    entry_key: str
    category: str
    content_id: str
    name: str
    grade_id: str
    grade_name: str
    quantity: int
    materials: tuple[tuple[str, int], ...] = ()
    #: 带先天灵宝的阵法是独立实例：灵宝编号与效果必须跟着条目走，否则发放回去就丢了加成。
    treasure_id: str = ""
    modifiers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SectAssetVault:
    sect_id: str
    name: str
    spirit_stones: int
    entries: tuple[SectAssetEntry, ...]


@dataclass(frozen=True)
class SectAssetTransfer:
    vault: str
    action: str
    entry: SectAssetEntry | None
    spirit_stones: int
    replayed: bool
    contribution: int = 0
    treasure_activation: InnateTreasureActivation | None = None


@dataclass(frozen=True)
class SectMaterialCost:
    category: str
    content_id: str
    grade_id: str
    quantity: int


@dataclass(frozen=True)
class SectProductGain:
    category: str
    content_id: str
    grade_id: str = ""
    quantity: int = 1
    materials: tuple[tuple[str, int], ...] = ()
    instance_key: str = ""


@dataclass(frozen=True)
class SectProductionAssetPlan:
    operations: tuple[SharedEntityMutation, ...]
    spirit_stones_before: int
    spirit_stones_after: int
    product_entry: SectAssetEntry | None


@dataclass(frozen=True)
class SectResourceGainPlan:
    operations: tuple[SharedEntityMutation, ...]
    spirit_stones_before: int
    spirit_stones_after: int
    entries: tuple[SectAssetEntry, ...]


@dataclass(frozen=True)
class SectFormationConsumptionPlan:
    entry: SectAssetEntry
    operation: SharedEntityMutation


__all__ = [
    "SectAssetConflictError",
    "SectAssetEntry",
    "SectAssetError",
    "SectAssetStatus",
    "SectAssetTransfer",
    "SectAssetVault",
    "SectFormationConsumptionPlan",
    "SectMaterialCost",
    "SectProductGain",
    "SectProductionAssetPlan",
    "SectResourceGainPlan",
]
