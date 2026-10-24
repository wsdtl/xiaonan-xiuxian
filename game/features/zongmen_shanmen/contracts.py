"""宗门山门玩法的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class GateFeatureError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class GateAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class GateCopy:
    text: Mapping[str, str]


@dataclass(frozen=True)
class GateResult:
    action: str
    participant_count: int


__all__ = ["GateAction", "GateCopy", "GateFeatureError", "GateResult"]
