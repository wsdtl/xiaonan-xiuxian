from __future__ import annotations

from dataclasses import dataclass


class GiftError(RuntimeError):
    """玩家赠送无法完成。"""


@dataclass(frozen=True)
class GiftSendCommand:
    user_id: str
    target_user_id: str
    request_id: str
    spirit_stones: int = 0
    item_id: str = ""
    grade_id: str = ""
    quantity: int = 0


@dataclass(frozen=True)
class GiftResult:
    request_id: str
    user_id: str
    target_user_id: str
    kind: str
    quantity: int
    item_id: str = ""
    grade_id: str = ""
    replayed: bool = False
    #: 展示用：物品名与品级名（由本服务按编号取；取不到就留空）。形状属于定义这个类型的包。
    item_name: str = ""
    grade_name: str = ""


__all__ = ["GiftError", "GiftResult", "GiftSendCommand"]
