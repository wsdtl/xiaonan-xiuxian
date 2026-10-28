"""宗门资源生产玩法的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.sect_production import SectProductionResult, SectProductionView


@dataclass(frozen=True)
class SectProductionAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class SectProductionEntry:
    """一次资源设施根命令的结果；分支与参数合规由玩法判定。"""

    kind: str
    view: SectProductionView | None = None
    result: SectProductionResult | None = None


__all__ = ["SectProductionAction", "SectProductionEntry"]
