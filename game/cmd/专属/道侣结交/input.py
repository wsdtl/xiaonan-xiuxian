"""道侣结交命令输入解析。"""

from __future__ import annotations

from game.features.daolv_jiejiao import CompanionQueryError
from game.features.presentation import ItemRefError, parse_item_ref


def gift_arguments(
    message: str, usage: str, quantity_hint: str
) -> tuple[str, str, str, int]:
    parts = str(message or "").split()
    if len(parts) < 2 or len(parts) > 4:
        raise CompanionQueryError(usage)
    companion, item = parts[:2]
    grade = ""
    quantity = 1
    # 新写法：品级并进物品词（<品级><物品>）；旧的「物品 品级 数量」仍然受理。
    try:
        ref = parse_item_ref(item)
    except ItemRefError:
        ref = None
    if ref is not None and ref.grade:
        item, grade = ref.item, ref.grade
    rest = parts[2:]
    if len(rest) == 1:
        if rest[0].isdecimal():
            quantity = int(rest[0])
        elif grade:
            raise CompanionQueryError(usage)
        else:
            grade = rest[0]
    elif len(rest) == 2:
        if grade:
            raise CompanionQueryError(usage)
        grade = rest[0]
        if not rest[1].isdecimal():
            raise CompanionQueryError(quantity_hint)
        quantity = int(rest[1])
    if quantity < 1:
        raise CompanionQueryError(quantity_hint)
    return companion, item, grade, quantity


__all__ = ["gift_arguments"]
