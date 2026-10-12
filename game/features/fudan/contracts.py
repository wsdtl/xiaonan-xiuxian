"""服丹玩法微服务的稳定请求与结果。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.innate_treasure import InnateTreasureActivation


class MedicineFeatureError(ValueError):
    """丹药、目标或当前状态不允许完成请求。"""


class MedicineFeatureConflictError(RuntimeError):
    """服丹期间角色或纳戒状态已经变化。"""


@dataclass(frozen=True)
class MedicineUseRequest:
    user_id: str
    request_id: str
    target: str
    medicine: str
    grade: str = ""


@dataclass(frozen=True)
class AutoMedicineRequest:
    user_id: str
    request_id: str
    target: str
    enabled: bool


@dataclass(frozen=True)
class MedicineUseResult:
    target: str
    target_name: str
    medicine_id: str
    medicine_name: str
    grade_id: str
    grade_name: str
    effect: str
    resource: str
    before: float
    after: float
    recovered: float
    replayed: bool
    treasure_activation: InnateTreasureActivation | None = None


@dataclass(frozen=True)
class AutoMedicineResult:
    target: str
    target_name: str
    enabled: bool
    replayed: bool




@dataclass(frozen=True)
class FudanAction:
    """服丹回执上的动作，字段名与 CommandAction 契约一致。"""

    action_id: str
    label: str
    command: str
    behavior: str
    style: str


__all__ = [
    "AutoMedicineRequest",
    "AutoMedicineResult",
    "MedicineFeatureConflictError",
    "MedicineFeatureError",
    "MedicineUseRequest",
    "MedicineUseResult",
]
