"""宗门资源生产玩法的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SectProductionAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


__all__ = ["SectProductionAction"]
