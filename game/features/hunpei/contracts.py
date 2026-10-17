"""婚配（生育）玩法的稳定公共契约。"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class HunpeiError(RuntimeError):
    """婚配请求无法完成。"""


class BirthDeniedError(HunpeiError):
    """不满足生育条件。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Newborn:
    """一个新生儿。"""

    code: str
    name: str
    sex: str
    dna: str
    bloodlines: tuple[str, ...]
    generation: int


@dataclass(frozen=True)
class BirthResult:
    """一次生育的结果。"""

    newborn: Newborn
    companion_code: str
    companion_name: str
    generation: int
    """生育发生在第几代。"""

    births_this_generation: int
    """本代已生育的胎数（含这一次）。"""

    births_limit: int
    """每代胎数上限。"""

    medicine_code: str
    """消耗的生育丹编号。"""

    medicine_name: str


@dataclass(frozen=True)
class BirthView:
    """生育前的状态视图：能不能生、为什么不能。"""

    companion_code: str
    companion_name: str
    can_birth: bool
    reason: str
    generation: int
    births_this_generation: int
    births_limit: int


@dataclass(frozen=True)
class BirthAsk:
    """一次求子请求被登记后的回执。"""

    request_id: str
    target_id: str
    target_name: str
    expires_at: float


@dataclass(frozen=True)
class BirthRequestView:
    """别人发给我的一条求子请求（展示用）。"""

    request_id: str
    asker_id: str
    asker_name: str
    created_at: str
    expires_at: float


@dataclass(frozen=True)
class BirthRespond:
    """我对一条求子请求的回应结果。"""

    request_id: str
    asker_id: str
    asker_name: str
    agreed: bool
    result: BirthResult | None


@dataclass(frozen=True)
class HunpeiCopy:
    """生育展示文案（来自展示数据集）。"""

    text: Mapping[str, Mapping[str, str]]
    icons: Mapping[str, str]
