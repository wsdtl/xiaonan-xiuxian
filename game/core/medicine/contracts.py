"""丹药核心微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class MedicineError(RuntimeError):
    """丹药定义或效果不符合正式规则。"""


@dataclass(frozen=True)
class MedicineStatus:
    initialized: bool
    recovery_count: int
    battle_count: int
    special_count: int
    auto_medicine_default: bool
    auto_medicine_threshold: float


@dataclass(frozen=True)
class RecoveryMedicine:
    medicine_id: str
    name: str
    grade_id: str
    grade_name: str
    resource: str
    recovery_percent: float
    grade_order: int


@dataclass(frozen=True)
class RecoveryMedicineStack:
    stack_key: str
    medicine_id: str
    name: str
    grade_id: str
    grade_name: str
    grade_order: int
    quantity: int
    resource: str
    recovery_percent: float


@dataclass(frozen=True)
class PreparedBattleMedicine:
    medicine_id: str
    grade_id: str


@dataclass(frozen=True)
class BattleMedicine:
    medicine_id: str
    name: str
    grade_id: str
    grade_name: str
    listeners: tuple[Mapping[str, object], ...]
    prepared_status: dict[str, object]
    grade_order: int


@dataclass(frozen=True)
class BreakthroughMedicine:
    """一颗突破丹的只读摘要（给「可突破」清单用）。

    候选一律从丹药实体里扫出来（`使用效果.目标境界` 相等），**不写死任何编号**。
    """

    medicine_id: str
    name: str
    permanent: tuple[tuple[str, int | float], ...] = ()


__all__ = [
    "BattleMedicine",
    "BreakthroughMedicine",
    "MedicineError",
    "MedicineStatus",
    "PreparedBattleMedicine",
    "RecoveryMedicine",
    "RecoveryMedicineStack",
]
