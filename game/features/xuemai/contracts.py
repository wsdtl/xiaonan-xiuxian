"""血脉玩法的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


class XuemaiError(RuntimeError):
    """血脉请求无法完成。"""


class GenealogyQueryError(XuemaiError, ValueError):
    """族谱查询无效。"""


@dataclass(frozen=True)
class GenealogyEntry:
    """族谱里的一个节点（一个人）。只增不改，记的是当时的事实。"""

    code: str
    """编号（句柄一律用编号）。"""

    blood_name: str
    """族谱名：出生时的名字。"""

    player_name: str
    """玩家名：继承之后的名字，不可改。"""

    sex: str
    """性别。"""

    generation: int
    """代次。传承前后为一代。"""

    father_code: str
    """父编号（无则空串）。"""

    mother_code: str
    """母编号（无则空串）。"""

    dna: str
    """12 位 DNA。"""

    retired: bool = False
    """是否已传位（旧壳进族谱时置 True）。"""


@dataclass(frozen=True)
class GenealogyView:
    """族谱视图：某个人名下的传承档案。"""

    self_code: str
    generation: int
    entries: Sequence[GenealogyEntry]


@dataclass(frozen=True)
class GenealogyCopy:
    """族谱展示文案（来自展示数据集，不写死在代码里）。"""

    text: Mapping[str, Mapping[str, str]]
    icons: Mapping[str, str]

@dataclass(frozen=True)
class SuccessionResult:
    """一次传位的结果。"""

    retired_code: str
    """旧壳编号（已记入族谱，标「已传位」）。"""

    retired_name: str
    """旧壳的族谱名。"""

    new_code: str
    """新壳编号（原新生儿）。"""

    new_name: str
    """新壳的族谱名。"""

    new_sex: str
    """新壳性别。"""

    generation: int
    """传位之后的代次。"""

    dna: str
    """新壳的 12 位 DNA。"""

    bloodlines: tuple[str, ...] = ()
    """按新 DNA 重算出的命中血脉名字（批 3 接上血脉定义后填充）。"""
