"""创建人物玩法的公共输入与结果。"""

from __future__ import annotations

from dataclasses import dataclass


class CreateCharacterError(RuntimeError):
    """创建人物玩法无法完成。"""


class InvalidCreateCharacterError(CreateCharacterError, ValueError):
    """玩家提交的创建信息无效。"""


class CharacterExistsError(CreateCharacterError):
    """该用户已经拥有角色。"""


@dataclass(frozen=True)
class CreateCharacterRequest:
    user_id: str
    request_id: str
    name: str
    gender: str
    #: 种族（天生那一层）：留空表示用人物规则里的初始种族（基准族人族）。
    race: str = ""


@dataclass(frozen=True)
class CreateCharacterResult:
    user_id: str
    name: str
    gender: str
    realm_id: str
    realm_name: str
    location_name: str
    xy: tuple[int, int]
    region: str
    terrain: str
    altitude: int
    initial_items: tuple[tuple[str, str, int], ...]
    replayed: bool
    race: str = ""


__all__ = [
    "CharacterExistsError",
    "CreateCharacterError",
    "CreateCharacterRequest",
    "CreateCharacterResult",
    "InvalidCreateCharacterError",
]
