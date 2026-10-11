"""道侣结交命令输入解析。"""

from __future__ import annotations

from game.features.daolv_jiejiao import CompanionQueryError


def gift_arguments(
    message: str, usage: str, quantity_hint: str
) -> tuple[str, str, str, int]:
    parts = str(message or "").split()
    if len(parts) < 2 or len(parts) > 4:
        raise CompanionQueryError(usage)
    companion, item = parts[:2]
    grade = ""
    quantity = 1
    rest = parts[2:]
    if len(rest) == 1:
        if rest[0].isdecimal():
            quantity = int(rest[0])
        else:
            grade = rest[0]
    elif len(rest) == 2:
        grade = rest[0]
        if not rest[1].isdecimal():
            raise CompanionQueryError(quantity_hint)
        quantity = int(rest[1])
    if quantity < 1:
        raise CompanionQueryError(quantity_hint)
    return companion, item, grade, quantity


__all__ = ["gift_arguments"]
