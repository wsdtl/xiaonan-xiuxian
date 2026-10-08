"""查看角色玩法的公共结果。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.character import CharacterProfile
from game.core.innate_treasure import InnateTreasure


class CharacterOverviewError(RuntimeError):
    """查看角色玩法无法完成。"""


class CharacterOverviewMissingError(CharacterOverviewError):
    """用户尚未创建人物。"""


@dataclass(frozen=True)
class CharacterOverviewResult:
    character: CharacterProfile
    xy: tuple[int, int]
    location_name: str
    region: str
    terrain: str
    altitude: int
    states: tuple[tuple[str, str], ...]
    cultivation_usage: tuple[tuple[str, int, int], ...]
    injuries: tuple[tuple[str, int], ...]
    innate_treasure: InnateTreasure | None
    innate_treasure_usage: tuple[int, int]
    #: 每个属性的基准值；展示层用它滤掉「等于基准、没有信息」的属性。
    attribute_baselines: tuple[tuple[str, float], ...] = ()


__all__ = [
    "CharacterOverviewError",
    "CharacterOverviewMissingError",
    "CharacterOverviewResult",
]
